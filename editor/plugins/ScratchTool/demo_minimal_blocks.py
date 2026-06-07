# -*- coding: utf-8 -*-
"""
CoronaEngine 最小化积木功能演示
===============================
平移 | 旋转 | 缩放 | 键盘鼠标 | if-else | while | for
"""

import sys, os, time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_EDITOR_DIR = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
_ENGINE_ROOT = os.path.dirname(_EDITOR_DIR)
if _EDITOR_DIR not in sys.path:
    sys.path.insert(0, _EDITOR_DIR)
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from CoronaCore.utils import corona_engine_scratch as CoronaEngine


# ============================================================
# 模拟输入
# ============================================================
def sim_key_press(key):
    CoronaEngine.update_key_state(key, True)
    print(f"  [输入] 按键按下: {key}")

def sim_key_release(key):
    CoronaEngine.update_key_state(key, False)
    print(f"  [输入] 按键释放: {key}")

def sim_mouse_press(x=0, y=0):
    CoronaEngine.update_mouse_state(True, x, y)
    print(f"  [输入] 鼠标按下: ({x}, {y})")

def sim_mouse_release(x=0, y=0):
    CoronaEngine.update_mouse_state(False, x, y)
    print(f"  [输入] 鼠标释放: ({x}, {y})")


# ============================================================
# 演示
# ============================================================
def demo_translate():
    print("\n" + "=" * 60)
    print("1. 平移 (Translate)")
    print("=" * 60)
    print(f"初始: X={CoronaEngine.X():.0f} Y={CoronaEngine.Y():.0f} Z={CoronaEngine.Z():.0f}")
    CoronaEngine.Xset(100); CoronaEngine.Yset(50); CoronaEngine.Zset(25)
    print(f"设置: X={CoronaEngine.X():.0f} Y={CoronaEngine.Y():.0f} Z={CoronaEngine.Z():.0f}")
    CoronaEngine.Xadd(10); CoronaEngine.Yadd(-5)
    print(f"偏移: X={CoronaEngine.X():.0f} Y={CoronaEngine.Y():.0f}")
    CoronaEngine.move(50)
    print(f"move: X={CoronaEngine.X():.0f}")
    print("OK")

def demo_rotate():
    print("\n" + "=" * 60)
    print("2. 旋转 (Rotate)")
    print("=" * 60)
    print(f"初始: rotX={CoronaEngine.rotationX():.0f} rotY={CoronaEngine.rotationY():.0f} rotZ={CoronaEngine.rotationZ():.0f}")
    CoronaEngine.rotateX(45)
    print(f"rotateX(45) -> rotX={CoronaEngine.rotationX():.0f}")
    CoronaEngine.rotateY(30)
    print(f"rotateY(30) -> rotY={CoronaEngine.rotationY():.0f}")
    CoronaEngine.rotateZ(90)
    print(f"rotateZ(90) -> rotZ={CoronaEngine.rotationZ():.0f}")
    CoronaEngine.face(180)
    print(f"face(180)  -> rotY={CoronaEngine.rotationY():.0f}")
    CoronaEngine.rotateZ(-45)
    print(f"rotateZ(-45)-> rotZ={CoronaEngine.rotationZ():.0f}")
    print("OK")

def demo_scale():
    print("\n" + "=" * 60)
    print("3. 缩放 (Scale)")
    print("=" * 60)
    sz = CoronaEngine.size()
    print(f"初始: {sz:.0f}")
    CoronaEngine.sizeSet(200)
    print(f"set200: {CoronaEngine.size():.0f}")
    CoronaEngine.sizeAdd(50)
    print(f"+50: {CoronaEngine.size():.0f}")
    CoronaEngine.sizeAdd(-30)
    print(f"-30: {CoronaEngine.size():.0f}")
    CoronaEngine.sizeSet(sz)
    print("OK")

def demo_input():
    print("\n" + "=" * 60)
    print("4. 键盘/鼠标检测")
    print("=" * 60)
    print(f"Space按下? {CoronaEngine.keyboard('Space')}")
    print(f"鼠标按下? {CoronaEngine.mouse1()}")
    sim_key_press('Space')
    print(f"Space按下? {CoronaEngine.keyboard('Space')}")
    sim_key_release('Space')
    print(f"Space按下? {CoronaEngine.keyboard('Space')}")
    sim_mouse_press(100, 200)
    print(f"鼠标按下? {CoronaEngine.mouse1()}")
    sim_mouse_release()
    print(f"鼠标按下? {CoronaEngine.mouse1()}")
    print(f"\n属性: X={CoronaEngine.attribute('X'):.0f} Y={CoronaEngine.attribute('Y'):.0f} SIZE={CoronaEngine.attribute('SIZE'):.0f}")
    print("OK")

def demo_control():
    print("\n" + "=" * 60)
    print("5. if-else / while / for")
    print("=" * 60)
    print("\n--- if-else ---")
    CoronaEngine.Xset(100)
    if CoronaEngine.X() > 50:
        print("X>50: 右移"); CoronaEngine.move(-30)
    else:
        print("X<=50: 左移"); CoronaEngine.move(30)
    print(f"结果 X={CoronaEngine.X():.0f}")

    print("\n--- while ---")
    n = 5
    while n > 0:
        print(f"  {n}...")
        n -= 1
    print("OK")

    print("\n--- for ---")
    for i in range(3):
        CoronaEngine.Xadd(5)
        print(f"  第{i+1}次 X+5 -> {CoronaEngine.X():.0f}")
    print("OK")

def demo_combined():
    print("\n" + "=" * 60)
    print("6. 组合: 空格键 -> 移动+变大")
    print("=" * 60)
    sim_key_press('Space')
    if CoronaEngine.keyboard('Space'):
        print("检测到空格!")
        for i in range(3):
            CoronaEngine.move(10)
            CoronaEngine.sizeAdd(10)
            print(f"  step{i+1}: X={CoronaEngine.X():.0f} sz={CoronaEngine.size():.0f}")
    sim_key_release('Space')

    print("\n鼠标按下 -> 旋转")
    sim_mouse_press()
    if CoronaEngine.mouse1():
        print("检测到鼠标!")
        CoronaEngine.rotateZ(45)
    sim_mouse_release()
    print(f"最终: X={CoronaEngine.X():.0f} sz={CoronaEngine.size():.0f}")
    print("OK")


def run():
    print("=" * 60)
    print("  CoronaEngine 最小化积木功能验证")
    print("  平移|旋转|缩放|键盘鼠标|if-else|while|for")
    print("=" * 60)
    try:
        demo_translate()
        demo_rotate()
        demo_scale()
        demo_input()
        demo_control()
        demo_combined()
        print("\n" + "=" * 60)
        print("  ALL PASS")
        print("=" * 60)
    except Exception as e:
        print(f"\nFAIL: {e}")
        import traceback
        traceback.print_exc()
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(run())