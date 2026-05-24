def load_ai_setting():
    """
    从同目录下的 ai_setting.yaml 文件中读取配置，
    并动态覆盖到 ai_config 中
    """
    try:
        import importlib

        from Quasar.ai_service.entrance import get_ai_entrance
        from Quasar.ai_agent.executor import reset_cached_agent

        get_ai_entrance()

        importlib.import_module(f"{__package__}.ai_setting")

        reset_cached_agent()
    except Exception as e:
        print(f"Error: 加载配置失败 - {e}")
