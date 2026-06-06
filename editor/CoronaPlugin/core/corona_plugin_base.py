from CoronaCore.core.corona_editor import CoronaEditor


class PluginBase:
    module_name = ""

    @classmethod
    def register_web(cls, module_name: str):
        """
        装饰器：注册 Python 模块到 CoronaEditor
        仅保留 module_name——UI 元数据已迁移至 Vue 的 pluginManifest.js
        """
        def decorator(c_cls):
            c_cls.module_name = module_name
            CoronaEditor.register_page(module_name, c_cls)
            return c_cls
        return decorator
