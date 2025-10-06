#!/usr/bin/env python3
"""
简单测试脚本
"""

import sys
import traceback
from hair_color_changer import HairColorChanger

def simple_test(original_path, mask_path):
    """
    简单测试一种颜色变换
    """
    try:
        changer = HairColorChanger()

        print("开始测试发色变换...")
        print(f"原图: {original_path}")
        print(f"Mask: {mask_path}")

        # 显示预设颜色
        print("\n可用颜色:")
        for key, value in changer.hair_colors.items():
            print(f"  {key}: {value['name']} (H:{value['h']}, S:{value['s']})")

        # 测试金色变换
        print(f"\n测试金色变换...")
        result = changer.change_hair_color(
            original_path,
            mask_path,
            "golden",  # 测试金色
            "test_result.jpg",
            debug=True
        )

        if result is not None:
            print("✅ 测试成功！结果保存为 test_result.jpg")
            print("✅ 调试信息保存在 debug_output/ 目录")
        else:
            print("❌ 测试失败")

    except Exception as e:
        print(f"❌ 发生错误: {e}")
        print("详细错误信息:")
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python simple_test.py <原图路径> <mask路径>")
        sys.exit(1)

    simple_test(sys.argv[1], sys.argv[2])