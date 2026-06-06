import logging
from typing import Dict, Any, List



try:
    from Quasar.ai_service.entrance import ai_entrance
    from Quasar.ai_config.ai_config import reload_ai_config

    @ai_entrance.collector.register_setting("chat")
    def CHAT_SETTINGS() -> Dict[str, Any]:
        return {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "system_prompt": """你是一个 AI 助手，可以帮助用户完成各种任务。""",
        }

    @ai_entrance.collector.register_setting("providers")
    def PROVIDERS() -> List[Dict[str, Any]]:
        return [
            {
                "name": "deepseek",
                "type": "openai-compatible",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "sk-461a028fe76242ad80a4eee53b9b2e35",
            },
            {
                "name": "grsai_image",
                "type": "grsai",
                "base_url": "https://grsai.dakka.com.cn/v1/api/generate",
                "api_key": "sk-02c743a4e5394a2ea4934f2132449eb9",
            },
        ]

    @ai_entrance.collector.register_setting("image")
    def IMAGE_SETTINGS() -> Dict[str, Any]:
        return {
            "enable": True,
            "provider": "grsai_image",
            "model": "gpt-image-2",
            "base_url": "https://grsai.dakka.com.cn/v1/api/generate",
        }

    @ai_entrance.collector.register_setting("hunyuan3d")
    def HUNYUAN_3D_SETTINGS() -> Dict[str, Any]:
        return {
            "enable": True,
            "api_key": "sk-YhvNa3WK8BydiBvq24u25MKe78gTG85ooOmpeFp748loExDJ",
            "region": "ap-guangzhou",
            "endpoint": "api.ai3d.cloud.tencent.com",
            "version": "pro",
            "result_format": "GLB",
            "enable_pbr": True,
            "model": "3.0",
            "generate_type": "Normal",
            "face_count": 500000,
            "request_timeout": 300.0,
            "poll_interval": 3.0,
            "poll_timeout": 600.0,
            "max_concurrent_generations": 2,
        }

    reload_ai_config()

    # 强制工具注册表重新发现（用户配置可能在 warmup 之后加载）
    from Quasar.ai_tools.registry import get_tool_registry
    get_tool_registry().reset_discovery()
    from Quasar.ai_agent.executor import reset_cached_agent
    reset_cached_agent()

except ImportError as e:
    logging.error(e)
