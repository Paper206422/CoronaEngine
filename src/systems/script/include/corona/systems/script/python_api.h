#pragma once

#include <Python.h>
#include <corona/systems/script/python_hotfix.h>
#include <nanobind/nanobind.h>

#include <atomic>
#include <chrono>
#include <filesystem>
#include <memory>
#include <shared_mutex>
#include <string>

namespace Corona::Script::Python {

struct PythonAPI {
    PythonAPI();

    ~PythonAPI();

    /**
     * @brief 主动关闭 Python 解释器
     *
     * 在 shutdown 中调用，避免在析构时阻塞
     */
    void shutdown();

    void begin_shutdown();

    void runPythonScript();
    static void checkPythonScriptChange();
    void checkReleaseScriptChange();
    void sendMessage(const std::string& message) const;

    /**
     * @brief 检查 Python 是否正在关闭
     */
    bool is_shutting_down() const { return shutting_down_.load(); }

    nanobind::object pStartFunc;   // callable 'start'
    nanobind::object pJsCallFunc;  // callable 'js_call'

   private:
    static const std::string codePath;

    PythonHotfix hotfixManger;
    mutable std::shared_mutex queMtx;

    int64_t lastHotReloadTime = 0;  // ms
    bool hasHotReload = false;
    std::atomic<bool> shutting_down_{false};  // 标记是否正在关闭

    nanobind::object pModule;      // module 'main'
    nanobind::object pFunc;        // callable 'run'
    nanobind::object messageFunc;  // callable 'put_queue'

    std::vector<std::string> moduleList;
    std::vector<std::string> callableList;

    PyConfig config{};  // 值初始化

    bool ensureInitialized();
    bool performHotReload();
    void invokeEntry(bool isReload) const;
    static int64_t nowMsec();
    static std::wstring str2wstr(const std::string& str);
    static std::string wstr2str(const std::wstring& wstr);
    static void copyModifiedFiles(const std::filesystem::path& sourceDir,
                                  const std::filesystem::path& destDir,
                                  int64_t checkTimeMs);
};
}  // namespace Corona::Script::Python
