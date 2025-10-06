#!/usr/bin/env python3
"""
图片对复制脚本
根据cache_index.json文件，将原始图片和处理后图片复制到新文件夹
命名格式：文件名_start.png（原始图片）、文件名_end.png（处理后图片）
"""

import json
import os
import shutil
from pathlib import Path
from PIL import Image



def expand_path(path_str):
    """
    展开路径中的~符号并转换为绝对路径
    """
    if path_str.startswith('~'):
        return os.path.expanduser(path_str)
    return os.path.abspath(path_str)


def get_filename_without_extension(filename):
    """
    获取不带扩展名的文件名
    """
    return Path(filename).stem


def resize_image_if_needed(image_path, target_path, min_size=512):
    """
    检查图片分辨率，如果不满足最小尺寸要求则调整为512x512

    Args:
        image_path: 源图片路径
        target_path: 目标图片路径
        min_size: 最小尺寸要求（默认512px）
    """
    try:
        with Image.open(image_path) as img:
            width, height = img.size

            # 检查是否需要调整尺寸
            if width < min_size or height < min_size:
                print(f"    图片尺寸 {width}x{height} 小于 {min_size}px，调整为 {min_size}x{min_size}")

                # 调整为512x512，保持纵横比并居中裁剪
                img_resized = img.resize((min_size, min_size), Image.Resampling.LANCZOS)

                # 转换为RGB模式以确保能保存为PNG
                if img_resized.mode != 'RGB':
                    img_resized = img_resized.convert('RGB')

                img_resized.save(target_path, 'PNG', quality=95)
            else:
                # 尺寸满足要求，直接复制
                shutil.copy2(image_path, target_path)

    except Exception as e:
        print(f"    调整图片尺寸时出错: {e}")
        # 如果调整失败，回退到直接复制
        shutil.copy2(image_path, target_path)


def copy_image_pairs(cache_index_path, output_dir):
    """
    根据cache_index.json复制图片对
    
    Args:
        cache_index_path: cache_index.json文件路径
        output_dir: 输出目录路径
    """
    # 读取cache index文件
    with open(cache_index_path, 'r', encoding='utf-8') as f:
        cache_data = json.load(f)
    
    # 创建输出目录
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    print(f"开始处理 {len(cache_data)} 个图片对...")
    
    success_count = 0
    error_count = 0
    
    for cache_id, item in cache_data.items():
        try:
            original_path = item['original_path']
            processed_path = item['processed_path']
            original_filename = item['original_filename']
            
            # 展开路径
            original_full_path = expand_path(original_path)
            processed_full_path = expand_path(processed_path)
            
            # 获取不带扩展名的文件名
            base_filename = get_filename_without_extension(original_filename)
            
            # 构造新的文件名
            start_filename = f"{base_filename}_start.png"
            end_filename = f"{base_filename}_end.png"
            
            # 目标路径
            start_target = output_path / start_filename
            end_target = output_path / end_filename
            
            # 复制原始图片（带尺寸检查和调整）
            if os.path.exists(original_full_path):
                print(f"✓ 处理原始图片: {original_filename} -> {start_filename}")
                resize_image_if_needed(original_full_path, start_target)
            else:
                print(f"⚠ 原始图片不存在: {original_full_path}")
                error_count += 1
                continue
            
            # 复制处理后图片
            if os.path.exists(processed_full_path):
                shutil.copy2(processed_full_path, end_target)
                print(f"✓ 复制处理后图片: {Path(processed_path).name} -> {end_filename}")
                success_count += 1
            else:
                print(f"⚠ 处理后图片不存在: {processed_full_path}")
                error_count += 1
                # 如果处理后图片不存在，删除已复制的原始图片
                if start_target.exists():
                    start_target.unlink()
                    print(f"✗ 删除孤立的原始图片: {start_filename}")
                
        except Exception as e:
            print(f"✗ 处理 {original_filename} 时出错: {str(e)}")
            error_count += 1
    
    print(f"\n处理完成!")
    print(f"成功复制: {success_count} 对图片")
    print(f"失败: {error_count} 个")
    print(f"输出目录: {output_path.absolute()}")


def main():
    """
    主函数
    """
    # 默认路径
    cache_index_path = "/Users/alex_wu/work/changyuan/codes/hairstyle_new/output/hair_color_generated/cache_index.json"
    output_dir = "output/hair_color_image_pairs"
    
    # 检查cache_index.json是否存在
    if not os.path.exists(cache_index_path):
        print(f"错误: 找不到cache_index.json文件: {cache_index_path}")
        return
    
    print(f"Cache index文件: {cache_index_path}")
    print(f"输出目录: {output_dir}")
    print("-" * 50)
    
    # 执行复制操作
    copy_image_pairs(cache_index_path, output_dir)


if __name__ == "__main__":
    main()
