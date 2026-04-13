#define PY_SSIZE_T_CLEAN
#include <corona/systems/script/python_api.h>
#include <corona/kernel/core/i_logger.h>
#include <nanobind/stl/string.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/events/imgui_system_events.h>
#include <corona/kernel/core/kernel_context.h>
#include <windows.h>

#include <iostream>
#include <ranges>
#include <regex>
#include <set>
#include <unordered_map>

#include "python_error_handler.cpp"
#include "python_path_config.cpp"

extern "C" PyObject* PyInit_CoronaEngine();

namespace Corona::Script::Python {

const std::string codePath = PathCfg::engine_root();

PythonAPI::PythonAPI() {
    CFW_LOG_DEBUG("PythonAPI: Constructor called");
}

PythonAPI::~PythonAPI() {
    if (!shutting_down_.load()) {
        if (Py_IsInitialized()) {
            shutdown();
        } else {
            (void)pStartFunc.release();
            (void)pJsCallFunc.release();
            (void)messageFunc.release();
            (void)pModule.release();
            (void)pFunc.release();
        }
    }
}

void PythonAPI::shutdown() {
    shutting_down_.store(true);

    if (!Py_IsInitialized()) {
        CFW_LOG_INFO("PythonAPI: Python not initialized, skipping shutdown");
        return;
    }

    CFW_LOG_INFO("PythonAPI: Shutting down Python interpreter...");

    CFW_LOG_INFO("PythonAPI: Releasing ownership of Python objects...");
    (void)pStartFunc.release();
    (void)pJsCallFunc.release();
    (void)messageFunc.release();
    (void)pModule.release();
    (void)pFunc.release();
    CFW_LOG_INFO("PythonAPI: Python object ownership released");

    CFW_LOG_INFO("PythonAPI: Skipping Py_FinalizeEx (process will clean up on exit)");

    PyConfig_Clear(&config);

    CFW_LOG_INFO("PythonAPI: Python shutdown complete");
}

int64_t PythonAPI::nowMsec() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

std::string PythonAPI::wstr2str(const std::wstring& wstr) {
    if (wstr.empty()) return {};
    int len = WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(), static_cast<int>(wstr.size()), nullptr, 0, nullptr, nullptr);
    if (len <= 0) return {};
    std::string out(static_cast<size_t>(len), '\0');
    WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(), static_cast<int>(wstr.size()), out.data(), len, nullptr, nullptr);
    return out;
}

bool PythonAPI::ensureInitialized() {
    if (Py_IsInitialized()) {
        return true;
    }

    CFW_LOG_INFO("PythonAPI: Initializing Python interpreter...");

    PyImport_AppendInittab("CoronaEngine", &PyInit_CoronaEngine);

    PyConfig_InitPythonConfig(&config);
    PyConfig_SetBytesString(&config, &config.home, CORONA_PYTHON_HOME_DIR);
    PyConfig_SetBytesString(&config, &config.pythonpath_env, CORONA_PYTHON_HOME_DIR);
    config.module_search_paths_set = 1;

    {
        std::string runtimePath = PathCfg::runtime_backend_abs();
        PyWideStringList_Append(&config.module_search_paths, str2wstr(runtimePath).c_str());
        PyWideStringList_Append(&config.module_search_paths, str2wstr(CORONA_PYTHON_MODULE_DLL_DIR).c_str());
        PyWideStringList_Append(&config.module_search_paths, str2wstr(CORONA_PYTHON_MODULE_LIB_DIR).c_str());
        PyWideStringList_Append(&config.module_search_paths, str2wstr(PathCfg::site_packages_dir()).c_str());
    }

    Py_InitializeFromConfig(&config);

    if (!Py_IsInitialized()) {
        CFW_LOG_CRITICAL("Python failed to initialize. Diagnostics:");
        try {
            auto print_wlist = [&](const char* title, const PyWideStringList& list) {
                CFW_LOG_ERROR("  {} ({})", title, list.length);
                for (Py_ssize_t i = 0; i < list.length; ++i) {
                    std::wstring ws = list.items[i] ? std::wstring(list.items[i]) : L"";
                    CFW_LOG_ERROR("    - {}", wstr2str(ws));
                }
            };
            CFW_LOG_ERROR("  home: {}", wstr2str(config.home));
            CFW_LOG_ERROR("  pythonpath_env: {}", wstr2str(config.pythonpath_env));
            print_wlist("module_search_paths", config.module_search_paths);
        } catch (...) {
            CFW_LOG_ERROR("Failed to print Python configuration diagnostics");
        }
        return false;
    }

    {
        nanobind::gil_scoped_acquire gil;
        try {
            //nanobind::module_ main_mod = nanobind::module_::import_("cpp_client");

            //nanobind::object init_func = nanobind::getattr(main_mod, "initialize");
            //init_func();

            //nanobind::object run_attr = nanobind::getattr(main_mod, "run");
            //nanobind::object putq_attr = nanobind::getattr(main_mod, "put_queue");

            //if (!nanobind::callable::check_(run_attr)) {
            //    CFW_LOG_ERROR("PythonAPI: 'run' attribute is not callable");
            //    return false;
            //}

            //pModule = std::move(main_mod);
            //pFunc = std::move(run_attr);
            //messageFunc = std::move(putq_attr);
            

            nanobind::module_ entrance = nanobind::module_::import_("main");
            nanobind::object editor = nanobind::getattr(entrance, "editor");
            nanobind::object start_attr = nanobind::getattr(entrance, "run");
            nanobind::object call_attr = nanobind::getattr(editor, "deal_func_from_js");
            nanobind::object log_attr = nanobind::getattr(editor, "show_log_on_js");
            pStartFunc = std::move(start_attr);
            pJsCallFunc = std::move(call_attr);
            messageFunc = std::move(log_attr);
            pStartFunc();
            if (auto* event_bus = Kernel::KernelContext::instance().event_bus()) {
                event_bus->publish<Events::ScriptFinishStartEvent>({});
            }
            CFW_LOG_INFO("PythonAPI: Python interpreter initialized successfully");
        } catch (const nanobind::python_error& e) {
            log_python_error(e);
            //pModule.reset();
            //pFunc.reset();
            //messageFunc.reset();
            pStartFunc.reset();
            pJsCallFunc.reset();
            messageFunc.reset();
            return false;
        }
    }
    return true;
}

bool PythonAPI::performHotReload() {
    int64_t currentTime = PythonHotfix::GetCurrentTimeMsec();  // ms
    constexpr int64_t kHotReloadIntervalMs = 100;              // 100ms
    if (currentTime - lastHotReloadTime <= kHotReloadIntervalMs || hotfixManger.packageSet.empty()) {
        return false;
    }

    CFW_LOG_DEBUG("PythonAPI: performHotReload triggered. packageSet.size={}", hotfixManger.packageSet.size());

    bool reloadedDeps = hotfixManger.ReloadPythonFile();
    if (!reloadedDeps) {
        CFW_LOG_DEBUG("PythonAPI: hotfixManger.ReloadPythonFile returned false");
        return false;
    }

    nanobind::gil_scoped_acquire gil;
    CFW_LOG_DEBUG("PythonAPI: reloading 'main' module (via importlib.reload)");

    try {
        nanobind::module_ importlib = nanobind::module_::import_("importlib");
        nanobind::object reload_func = nanobind::getattr(importlib, "reload");

        nanobind::module_ mod = nanobind::module_::import_("main");
        (void)reload_func(mod);

        nanobind::object editor = nanobind::getattr(mod, "editor");
        nanobind::object start_attr = nanobind::getattr(mod, "run");
        nanobind::object call_attr = nanobind::getattr(editor, "deal_func_from_js");
        nanobind::object log_attr = nanobind::getattr(editor, "show_log_on_js");
        pStartFunc = std::move(start_attr);
        pJsCallFunc = std::move(call_attr);
        messageFunc = std::move(log_attr);
      /*  nanobind::object newFunc = nanobind::getattr(mod, "run");
        if (!nanobind::callable::check_(newFunc)) {
            CFW_LOG_WARNING("PythonAPI: new run attribute is not callable");
            return false;
        }
        nanobind::object newMsg = nanobind::getattr(mod, "put_queue");

        pModule = std::move(mod);
        pFunc = std::move(newFunc);
        messageFunc = std::move(newMsg);*/
    } catch (const nanobind::python_error& e) {
        CFW_LOG_ERROR("PythonAPI: reload(main) failed");
        log_python_error(e);
        return false;
    }

    lastHotReloadTime = currentTime;
    hasHotReload = true;
    CFW_LOG_DEBUG("PythonAPI: performHotReload finished successfully");
    return true;
}

void PythonAPI::invokeEntry(bool isReload) const {
    // 如果正在关闭，不执行
    if (shutting_down_.load()) {
        return;
    }

    if (!messageFunc.is_valid()) {
        return;
    }
    nanobind::gil_scoped_acquire gil;

    try {
        //(void)pFunc(isReload ? 1 : 0);
        messageFunc();
    } catch (const nanobind::python_error& e) {
        log_python_error(e);
    }
}

void PythonAPI::sendMessage(const std::string& message) const {
    //if (!messageFunc.is_valid()) {
    //    return;
    //}
    //nanobind::gil_scoped_acquire gil;

    //try {
    //    (void)messageFunc(message.c_str());
    //} catch (const nanobind::python_error& e) {
    //    log_python_error(e);
    //}
}

void PythonAPI::runPythonScript() {
    // 如果正在关闭，不执行任何 Python 代码
    if (shutting_down_.load()) {
        return;
    }

    if (!ensureInitialized()) {
        CFW_LOG_ERROR("PythonAPI: Python initialization failed");
        return;
    }

    bool reloaded = false;
    {
        std::unique_lock lk(queMtx);
        reloaded = performHotReload();
        if (!reloaded && !hotfixManger.packageSet.empty()) {
            hasHotReload = false;
        }
    }

    // 再次检查是否正在关闭
    if (shutting_down_.load()) {
        return;
    }

    invokeEntry(reloaded);
}

void PythonAPI::checkPythonScriptChange() {
    const std::string& sourcePath = PathCfg::editor_backend_abs();
    const std::string runtimePath = PathCfg::runtime_backend_abs();
    int64_t checkTime = PythonHotfix::GetCurrentTimeMsec();
    CFW_LOG_DEBUG("PythonAPI: checkPythonScriptChange: src={}, dst={}, t={}", sourcePath, runtimePath, checkTime);
    copyModifiedFiles(sourcePath, runtimePath, checkTime);
}

void PythonAPI::checkReleaseScriptChange() {
    static int64_t lastCheckTime = 0;
    static std::unordered_map<std::string, int64_t> lastProcessedMtime;  // mod -> last mtime processed

    int64_t currentTime = PythonHotfix::GetCurrentTimeMsec();
    if (currentTime - lastCheckTime < 100) {
        return;
    }
    lastCheckTime = currentTime;

    std::queue<std::unordered_set<std::string>> messageQue;
    const std::string runtimePathStr = Corona::Script::Python::PathCfg::runtime_backend_abs();
    const std::filesystem::path runtimePath(runtimePathStr);
    PythonHotfix::TraverseDirectory(runtimePathStr, messageQue, currentTime);

    if (messageQue.empty()) {
        return;
    }

    std::unique_lock lk(queMtx);
    const auto& mods = messageQue.front();
    
    // Build module list string for logging
    std::string moduleListStr;
    bool first = true;
    for (const auto& m : mods) {
        if (!first) moduleListStr += ", ";
        moduleListStr += m;
        first = false;
    }
    CFW_LOG_DEBUG("PythonAPI: detected modified modules ({}): {}", mods.size(), moduleListStr);

    auto modToPath = [&](const std::string& mod) {
        std::string rel = mod;  // replace '.' with '/'
        std::ranges::replace(rel, '.', '/');
        return runtimePath / (rel + ".py");
    };

    for (const auto& mod : mods) {
        int64_t fileMtimeMs = 0;
        std::error_code ec;
        const auto filePath = modToPath(mod);
        auto ftime = std::filesystem::last_write_time(filePath, ec);
        if (!ec) {
            auto sysTime = std::chrono::clock_cast<std::chrono::system_clock>(ftime);
            fileMtimeMs = std::chrono::duration_cast<std::chrono::milliseconds>(sysTime.time_since_epoch()).count();
        }

        auto it = lastProcessedMtime.find(mod);
        if (it != lastProcessedMtime.end() && fileMtimeMs > 0 && fileMtimeMs <= it->second) {
            CFW_LOG_DEBUG("PythonAPI: skip duplicate module in window: '{}' mtime={} lastProcessed={}", mod, fileMtimeMs, it->second);
            continue;
        }

        if (!hotfixManger.packageSet.contains(mod)) {
            hotfixManger.packageSet.emplace(mod, currentTime);
            CFW_LOG_DEBUG("PythonAPI: packageSet.emplace: '{}' @{}", mod, currentTime);
        } else {
            CFW_LOG_DEBUG("PythonAPI: packageSet already contains: '{}' (skip)", mod);
        }
        if (fileMtimeMs > 0) {
            lastProcessedMtime[mod] = fileMtimeMs;
        }
    }
}

std::wstring PythonAPI::str2wstr(const std::string& str) {
    if (str.empty()) {
        return {};
    }
    int wlen = MultiByteToWideChar(CP_UTF8, 0, str.c_str(), static_cast<int>(str.size()), nullptr, 0);
    if (wlen <= 0) {
        return {};
    }
    std::wstring w(static_cast<size_t>(wlen), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, str.c_str(), static_cast<int>(str.size()), w.data(), wlen);
    return w;
}

void PythonAPI::copyModifiedFiles(const std::filesystem::path& sourceDir,
                                  const std::filesystem::path& destDir,
                                  int64_t checkTimeMs) {
    static const std::set<std::string> skip = {
        "__pycache__", "__init__.py", ".pyc", "StaticComponents.py"};
    static std::unordered_map<std::string, int64_t> lastCopiedMtime;

    for (const auto& entry : std::filesystem::recursive_directory_iterator(sourceDir)) {
        if (!entry.is_regular_file()) {
            continue;
        }
        const auto& filePath = entry.path();
        std::string fileName = filePath.filename().string();
        if (!PythonHotfix::EndsWith(fileName, ".py")) {
            continue;
        }
        bool skipFile = std::ranges::any_of(skip, [&](const std::string& s) {
            return PythonHotfix::EndsWith(fileName, s);
        });
        if (skipFile) {
            continue;
        }

        try {
            auto ftime = std::filesystem::last_write_time(filePath);
            auto sysTime = std::chrono::clock_cast<std::chrono::system_clock>(ftime);
            int64_t modifyMs = std::chrono::duration_cast<std::chrono::milliseconds>(sysTime.time_since_epoch()).count();

            auto srcKey = filePath.string();
            auto it = lastCopiedMtime.find(srcKey);
            bool newerThanLastCopy = (it == lastCopiedMtime.end()) || (modifyMs > it->second);
            if (checkTimeMs - modifyMs <= PythonHotfix::kFileRecentWindowMs && newerThanLastCopy) {
                auto relativePath = std::filesystem::relative(filePath, sourceDir);
                auto destFilePath = destDir / relativePath;
                std::filesystem::create_directories(destFilePath.parent_path());
                std::filesystem::copy_file(filePath, destFilePath,
                                           std::filesystem::copy_options::overwrite_existing);
                std::filesystem::last_write_time(destFilePath, ftime);

                lastCopiedMtime[srcKey] = modifyMs;

                std::string modName = destFilePath.string();
                PythonHotfix::NormalizeModuleName(modName);
                CFW_LOG_DEBUG("PythonAPI: copied recent file: {} -> {}, module='{}' src_mtime={}", 
                             filePath.string(), destFilePath.string(), modName, modifyMs);
            }
        } catch (const std::exception& e) {
            CFW_LOG_ERROR("PythonAPI: File copy error: {}", e.what());
        }
    }
}
}  // namespace Corona::Script::Python
