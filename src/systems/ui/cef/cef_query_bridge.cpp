#include "cef_client.h"

#include <iostream>
#include <stdexcept>

namespace Corona::Systems::UI {

BrowserSideJSHandler::~BrowserSideJSHandler() {
    PyGILState_STATE state = PyGILState_Ensure();
    Py_XDECREF(pFunc_);
    PyGILState_Release(state);
}

void BrowserSideJSHandler::initialize_python() {
    if (!Py_IsInitialized()) {
        Py_Initialize();
        PyEval_SaveThread();
    }

    PyGILState_STATE state = PyGILState_Ensure();
    PyObject* pModule = nullptr;

    try {
        PyRun_SimpleString("import sys");
        PyRun_SimpleString("import os");
        PyRun_SimpleString("sys.path.insert(0, os.path.join(os.getcwd(), 'CabbageEditor'))");

        PyObject* pName = PyUnicode_FromString("main");
        if (!pName) {
            throw std::runtime_error("Failed to create module name");
        }

        pModule = PyImport_Import(pName);
        Py_DECREF(pName);

        if (!pModule) {
            PyErr_Print();
            PyGILState_Release(state);
            throw std::runtime_error("Failed to import Python module 'main'");
        }

        PyObject* pClass = PyObject_GetAttrString(pModule, "editor");
        if (!pClass) {
            Py_DECREF(pModule);
            PyErr_Print();
            PyGILState_Release(state);
            throw std::runtime_error("Failed to get 'editor' attribute from module");
        }

        if (PyCallable_Check(pClass)) {
            pFunc_ = PyObject_GetAttrString(pClass, "deal_func_from_js");
        }

        Py_DECREF(pClass);
        Py_DECREF(pModule);

    } catch (const std::exception&) {
        if (pModule) {
            Py_DECREF(pModule);
        }
        PyErr_Print();
        PyGILState_Release(state);
        throw;
    }

    PyGILState_Release(state);
}

bool BrowserSideJSHandler::OnQuery(CefRefPtr<CefBrowser> browser,
                                   CefRefPtr<CefFrame> frame,
                                   int64_t query_id,
                                   const CefString& request,
                                   bool persistent,
                                   CefRefPtr<Callback> callback) {
    CEF_REQUIRE_UI_THREAD();
    std::string req = request.ToString();
    VUE_LOG_DEBUG("Received query: {}", req.c_str());

    if (!Py_IsInitialized()) {
        Py_Initialize();
        PyEval_SaveThread();
    }

    PyGILState_STATE gstate = PyGILState_Ensure();

    try {
        if (!pFunc_) {
            initialize_python();
        }

        PyObject* args = PyTuple_Pack(1, PyUnicode_FromString(req.c_str()));
        PyObject* object = PyObject_CallObject(pFunc_, args);
        Py_DECREF(args);

        if (!object) {
            PyErr_Print();
            VUE_LOG_ERROR("Python function call failed for request");
            callback->Failure(0, "Python function call failed");
        } else {
            if (PyUnicode_Check(object)) {
                const char* result = PyUnicode_AsUTF8(object);
                callback->Success(result);
            } else {
                if (PyObject* str_obj = PyObject_Str(object)) {
                    const char* result = PyUnicode_AsUTF8(str_obj);
                    callback->Success(result);
                    Py_DECREF(str_obj);
                }
            }
            Py_DECREF(object);
        }

    } catch (const std::exception& e) {
        std::cerr << "Exception in OnQuery: " << e.what() << std::endl;
        callback->Failure(0, e.what());
        PyGILState_Release(gstate);
        return false;
    }

    PyGILState_Release(gstate);
    return true;
}

}  // namespace Corona::Systems::UI