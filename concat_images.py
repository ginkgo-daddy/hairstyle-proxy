#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片横向拼接脚本
将两个文件夹中的图片进行横向拼接（长边和长边拼接）
同一个文件夹下的图片不拼接
"""

import os
import glob
from PIL import Image
import itertools
from pathlib import Path
import hashlib
import re
import random
import shutil
def get_file_hash(file_path):
    """计算文件的MD5哈希值"""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        print(f"计算文件哈希失败: {e}")
        return None

def get_image_files(folder_path):
    """获取文件夹中的所有图片文件"""
    image_extensions = ['*.png', '*.jpg', '*.jpeg', '*.bmp', '*.tiff', '*.webp']
    image_files = []
    
    for ext in image_extensions:
        image_files.extend(glob.glob(os.path.join(folder_path, ext)))
        image_files.extend(glob.glob(os.path.join(folder_path, ext.upper())))
    
    # 排除cache_index.json等非图片文件
    image_files = [f for f in image_files if not f.endswith('.json')]
    
    return sorted(image_files)


def find_corresponding_end_files(hairstyle_name, user_name, results_folders):
    """
    根据start文件名找到对应的end文件
    
    Args:
        hairstyle_name: 发型文件名（不含扩展名）
        user_name: 用户文件名（不含扩展名）
        results_folders: 结果文件夹列表
    
    Returns:
        list: 找到的end文件路径列表
    """
    end_files = []
    
    # 清理文件名，移除_gemini_processed后缀和hash值
    clean_hairstyle = hairstyle_name.replace('_gemini_processed', '')
    clean_user = user_name.replace('_gemini_processed', '')
    
    # 移除hash值（8位十六进制字符串）
    clean_hairstyle = re.sub(r'_[a-f0-9]{8}$', '', clean_hairstyle)
    clean_user = re.sub(r'_[a-f0-9]{8}$', '', clean_user)
    
    for results_folder in results_folders:
        if not os.path.exists(results_folder):
            continue
            
        # 获取文件夹中的所有图片文件
        result_files = get_image_files(results_folder)
        
        # 确定性别前缀
        gender = "man" if "man" in results_folder else "woman"
        
        for result_file in result_files:
            filename = os.path.basename(result_file)
            
            # 检查是否为result文件（不是combined_all文件）
            if not filename.endswith('_result_0.png') and not filename.endswith('_result_1.png') and \
               not filename.endswith('_result_2.png') and not filename.endswith('_result_3.png'):
                continue
            
            # 分析文件名结构：{gender}_{user_file}_{hairstyle_file}_result_{i}.png
            # 移除扩展名和result部分
            name_without_ext = filename.replace('.png', '')
            parts = name_without_ext.split('_result_')
            if len(parts) != 2:
                continue
                
            base_name = parts[0]  # gender_user_file_hairstyle_file
            result_index = parts[1]  # 0, 1, 2, 3
            
            # 移除gender前缀
            if base_name.startswith(f"{gender}_"):
                base_name = base_name[len(f"{gender}_"):]
            
            # 尝试匹配用户文件和发型文件
            # 由于文件名可能包含特殊字符，我们使用模糊匹配
            if clean_user in base_name and clean_hairstyle in base_name:
                end_files.append(result_file)
                print(f"✅ 找到对应的end文件: {filename}")
    
    return end_files


def save_random_end_file(end_files, hairstyle_name, user_name, output_folder):
    """
    从找到的end文件中随机选择一个并保存到输出文件夹
    
    Args:
        end_files: 找到的end文件路径列表
        hairstyle_name: 发型文件名（不含扩展名）
        user_name: 用户文件名（不含扩展名）
        output_folder: 输出文件夹路径
    
    Returns:
        str: 保存的end文件路径，如果没有文件则返回None
    """
    if not end_files:
        return None
    
    # 随机选择一个end文件
    selected_end_file = random.choice(end_files)
    
    # 清理文件名，移除_gemini_processed后缀和hash值
    clean_hairstyle = hairstyle_name.replace('_gemini_processed', '')
    clean_user = user_name.replace('_gemini_processed', '')
    
    # 移除hash值（8位十六进制字符串）
    clean_hairstyle = re.sub(r'_[a-f0-9]{8}$', '', clean_hairstyle)
    clean_user = re.sub(r'_[a-f0-9]{8}$', '', clean_user)
    
    # 生成end文件名
    end_filename = f"{clean_hairstyle}__concat__{clean_user}_end.png"
    end_output_path = os.path.join(output_folder, end_filename)
    
    try:
        # 复制选中的end文件到输出文件夹
        shutil.copy2(selected_end_file, end_output_path)
        print(f"✅ 保存end文件: {os.path.basename(selected_end_file)} -> {end_filename}")
        return end_output_path
    except Exception as e:
        print(f"❌ 保存end文件失败: {str(e)}")
        return None


def resize_to_same_height(img1, img2):
    """将两张图片调整到相同的高度（保持纵横比）"""
    # 获取两张图片的尺寸
    w1, h1 = img1.size
    w2, h2 = img2.size
    
    # 选择较小的高度作为目标高度
    target_height = min(h1, h2)
    
    # 计算新的宽度（保持纵横比）
    new_w1 = int(w1 * target_height / h1)
    new_w2 = int(w2 * target_height / h2)
    
    # 调整图片大小
    img1_resized = img1.resize((new_w1, target_height), Image.Resampling.LANCZOS)
    img2_resized = img2.resize((new_w2, target_height), Image.Resampling.LANCZOS)
    
    return img1_resized, img2_resized


def concat_images_horizontal(img1_path, img2_path, output_path):
    """横向拼接两张图片"""
    try:
        # 打开图片
        img1 = Image.open(img1_path)
        img2 = Image.open(img2_path)
        
        # 转换为RGB模式（确保兼容性）
        if img1.mode != 'RGB':
            img1 = img1.convert('RGB')
        if img2.mode != 'RGB':
            img2 = img2.convert('RGB')
        
        # 调整到相同高度
        img1_resized, img2_resized = resize_to_same_height(img1, img2)
        
        # 创建新图片（宽度为两张图片宽度之和）
        total_width = img1_resized.width + img2_resized.width
        max_height = img1_resized.height  # 现在两张图片高度相同
        
        combined_img = Image.new('RGB', (total_width, max_height), color='white')
        
        # 粘贴图片
        combined_img.paste(img1_resized, (0, 0))
        combined_img.paste(img2_resized, (img1_resized.width, 0))
        
        # 保存结果
        combined_img.save(output_path, 'PNG', quality=95)
        return True
        
    except Exception as e:
        print(f"❌ 拼接失败: {os.path.basename(img1_path)} + {os.path.basename(img2_path)}, 错误: {str(e)}")
        return False


def main():
    """主函数"""
    # 定义文件夹路径
    hairstyle_folder = "/Users/alex_wu/work/changyuan/codes/hairstyle_new/outputs/gemini_processed_hairstyle"
    user_folder = "/Users/alex_wu/work/changyuan/codes/hairstyle_new/outputs/gemini_processed_user"
    output_folder = "/Users/alex_wu/work/changyuan/codes/hairstyle_new/outputs/concatenated_images"
    
    # 定义结果文件夹路径
    results_folders = [
        "/Users/alex_wu/work/changyuan/codes/hairstyle_new/outputs/results_man_0924_",
        "/Users/alex_wu/work/changyuan/codes/hairstyle_new/outputs/results_woman_0924_"
    ]
    
    # 创建输出文件夹
    os.makedirs(output_folder, exist_ok=True)
    
    # 获取两个文件夹中的图片文件
    hairstyle_images = get_image_files(hairstyle_folder)
    user_images = get_image_files(user_folder)
    
    print(f"📁 发型图片文件夹包含 {len(hairstyle_images)} 张图片")
    print(f"📁 用户图片文件夹包含 {len(user_images)} 张图片")
    print(f"📁 输出文件夹: {output_folder}")
    print("=" * 60)
    
    # 检查是否有图片文件
    if not hairstyle_images:
        print("❌ 发型图片文件夹中没有找到图片文件")
        return
    
    if not user_images:
        print("❌ 用户图片文件夹中没有找到图片文件")
        return
    
    # 进行所有可能的组合拼接
    success_count = 0
    total_count = 0
    
    for hairstyle_img in hairstyle_images:
        for user_img in user_images:
            total_count += 1
            
            # 生成输出文件名
            hairstyle_name = Path(hairstyle_img).stem
            user_name = Path(user_img).stem
            output_filename = f"{hairstyle_name}__concat__{user_name}_start.png".replace(f"_gemini_processed", "").replace(f"_gemini_processed", "")
            # 使用正则表达式去掉文件名中的hash值
            output_filename = re.sub(r'_[a-f0-9]{8}', '', output_filename)
            output_path = os.path.join(output_folder, output_filename)
            
            # 先查找对应的end文件
            print(f"🔍 查找对应的end文件...")
            end_files = find_corresponding_end_files(hairstyle_name, user_name, results_folders)
            
            if not end_files:
                print(f"❌ 未找到对应的end文件，跳过此组合: {os.path.basename(hairstyle_img)} + {os.path.basename(user_img)}")
                print("-" * 40)
                continue
            
            print(f"📁 找到 {len(end_files)} 个对应的end文件:")
            for end_file in end_files:
                print(f"   📄 {os.path.basename(end_file)}")
            
            # 检查start文件是否已存在
            if os.path.exists(output_path):
                print(f"⏭️  跳过已存在的start文件: {output_filename}")
                success_count += 1
                
                # 随机选择并保存一个end文件
                saved_end_file = save_random_end_file(end_files, hairstyle_name, user_name, output_folder)
                if saved_end_file:
                    print(f"💾 已随机选择并保存end文件: {os.path.basename(saved_end_file)}")
                print("-" * 40)
                continue
            
            # 进行拼接（只有找到end文件时才拼接）
            if concat_images_horizontal(hairstyle_img, user_img, output_path):
                success_count += 1
                print(f"✅ 成功创建start文件: {output_filename}")
                
                # 随机选择并保存一个end文件
                saved_end_file = save_random_end_file(end_files, hairstyle_name, user_name, output_folder)
                if saved_end_file:
                    print(f"💾 已随机选择并保存end文件: {os.path.basename(saved_end_file)}")
            else:
                print(f"❌ 拼接失败，删除可能存在的start文件")
                if os.path.exists(output_path):
                    os.remove(output_path)
            
            print("-" * 40)
    
    print("=" * 60)
    print(f"🎉 拼接完成! 成功: {success_count}/{total_count}")
    print(f"📂 输出目录: {output_folder}")


if __name__ == "__main__":
    main()
