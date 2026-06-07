import os
import tkinter as tk
from tkinter import filedialog

# 文件类型配置表
_FILE_TYPE_CONFIG = {
    "project": ("选择项目配置文件","项目配置文件 (*.ini)"),
    "model": ("选择模型文件", "3D模型文件 (*.obj *.fbx *.3ds *.dae *.usd *.usda *.usdz *.gltf *.glb *.usdc *.stl)"),
    "multimedia": ("选择多媒体文件", "多媒体文件 (*.mp4 *.avi *.mov *.mp3 *.wav)"),
    "scene": ("选择场景文件", "场景文件 (*.json)"),
    "actor": ("选择单位文件", "单位文件 (*.actor)"),
    "script": ("选择脚本文件", "脚本文件 (*.py)"),
    "terrain": ("选择地形文件", "地形文件 (*.terrain)"),
}

class FileHandler:
    """使用Python原生tkinter的文件处理器"""

    @staticmethod
    def init_tkinter():
        """初始化tkinter（只创建隐藏窗口）"""
        root = tk.Tk()
        root.withdraw()  # 隐藏主窗口
        root.attributes('-topmost', True)  # 置顶
        root.update()  # 强制处理所有待处理的事件
        root.lift()  # 提升到最前
        root.focus_force()  # 强制获取焦点
        return root

    @staticmethod
    def open_file(caption="打开文件", file_types=None, default_dir=None, read_content=True, return_relative_path=False):
        """
        打开文件对话框
        file_types: [(描述, 扩展), ...] 如 [("文本文件", "*.txt"), ("所有文件", "*.*")]
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[FileHandler.open_file] Called with caption={caption}, default_dir={default_dir}")

        if default_dir is None:
            default_dir = os.getcwd()

        if file_types is None:
            file_types = [("所有文件", "*.*")]
        else:
            # 解析文件类型参数
            file_types = FileHandler._parse_file_types(file_types)

        # 初始化tkinter
        logger.info(f"[FileHandler.open_file] Initializing tkinter...")
        root = FileHandler.init_tkinter()

        try:
            logger.info(f"[FileHandler.open_file] Showing file dialog...")
            # 显示文件对话框
            file_path = filedialog.askopenfilename(
                title=caption,
                initialdir=default_dir,
                filetypes=file_types,
                parent=root
            )
            logger.info(f"[FileHandler.open_file] Dialog returned: {file_path}")
        finally:
            root.destroy()  # 确保窗口被销毁
            logger.info(f"[FileHandler.open_file] Tkinter destroyed")

        if not file_path:
            return None, None

        # 处理路径
        if return_relative_path:
            try:
                file_path = os.path.relpath(file_path, default_dir).replace('\\', '/')
            except ValueError:
                # 跨盘符（如 E: vs C:）无法计算相对路径，保留绝对路径
                file_path = file_path.replace('\\', '/')

        if not read_content:
            return None, file_path

        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
            return content, file_path
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='gbk') as file:
                    content = file.read()
                return content, file_path
            except Exception as e:
                print(f"读取文件失败: {str(e)}")
        except Exception as e:
            print(f"读取文件失败: {str(e)}")

        return None, None

    @staticmethod
    def save_file(content, caption="保存文件", file_types=None,
                  default_dir=None, default_filename=""):
        """保存文件对话框"""
        if default_dir is None:
            default_dir = os.getcwd()

        if file_types is None:
            file_types = [("所有文件", "*.*")]

        # 初始化tkinter
        root = FileHandler.init_tkinter()

        try:
            # 显示保存对话框
            file_path = filedialog.asksaveasfilename(
                title=caption,
                initialdir=default_dir,
                initialfile=default_filename,
                filetypes=file_types,
                defaultextension=file_types[0][1] if file_types else "",
                parent=root
            )
        finally:
            root.destroy()

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as file:
                    file.write(content)
                return file_path
            except Exception as e:
                print(f"保存文件失败: {str(e)}")

        return None

    @staticmethod
    def choose_save_path(caption="保存文件", file_types=None,
                         default_dir=None, default_filename="", return_relative_path=False):
        """仅选择保存路径，不写入文件内容"""
        if default_dir is None:
            default_dir = os.getcwd()

        if file_types is None:
            file_types = [("所有文件", "*.*")]
        else:
            file_types = FileHandler._parse_file_types(file_types)

        root = FileHandler.init_tkinter()

        default_ext = ""
        if file_types and len(file_types[0]) > 1:
            pattern = file_types[0][1]
            if isinstance(pattern, str) and pattern.startswith("*."):
                default_ext = pattern[1:]

        try:
            file_path = filedialog.asksaveasfilename(
                title=caption,
                initialdir=default_dir,
                initialfile=default_filename,
                filetypes=file_types,
                defaultextension=default_ext,
                parent=root
            )
        finally:
            root.destroy()

        if not file_path:
            return ""

        if return_relative_path:
            try:
                file_path = os.path.relpath(file_path, default_dir).replace('\\', '/')
            except ValueError:
                file_path = file_path.replace('\\', '/')

        return file_path

    @staticmethod
    def open_directory(caption="选择目录", default_dir=None):
        """打开目录选择对话框"""
        if default_dir is None:
            default_dir = os.getcwd()

        root = FileHandler.init_tkinter()
        try:
            directory = filedialog.askdirectory(
                title=caption,
                initialdir=default_dir,
                parent=root
            )
        finally:
            root.destroy()

        return directory

    @staticmethod
    def _parse_file_types(file_param):
        """
        解析文件类型参数，支持多种格式：
        1. Qt格式字符串: "描述 (模式)"
        2. tkinter格式列表: [("描述", "模式"), ...]
        3. 直接传入扩展名: "*.txt *.log"
        """
        if isinstance(file_param, list):
            # 已经是tkinter格式
            return file_param

        if isinstance(file_param, str):
            if file_param == "所有文件 (*.*)":
                return [("所有文件", "*.*")]

            # 尝试解析Qt格式: "描述 (模式)"
            if "(" in file_param and ")" in file_param:
                try:
                    # 提取描述和模式
                    desc_end = file_param.rfind("(")
                    desc = file_param[:desc_end].strip()
                    pattern = file_param[desc_end:].strip("() ").strip()

                    if desc and pattern:
                        return [(desc, pattern)]
                    else:
                        # 如果没有描述，使用模式作为描述
                        return [("文件", pattern)]
                except:
                    pass

            # 如果只是扩展名，直接使用
            if "*" in file_param:
                return [("文件", file_param)]

        # 默认返回所有文件
        return [("所有文件", "*.*")]



if __name__ == '__main__':
    print(os.path.relpath(r"D:\vs_workspace\CoronaEngine\assets\chair\modern chair 11 fbx.FBX",r"D:\vs_workspace\New_Corona_Project\Scene"))