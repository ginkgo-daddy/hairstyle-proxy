#!/usr/bin/env python3
"""
检查现有缓存状态
显示已缓存的图片信息和统计
"""

import os
import json
from datetime import datetime
from pathlib import Path

def format_file_size(size_bytes):
    """格式化文件大小"""
    if size_bytes == 0:
        return "0B"
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.1f}{size_names[i]}"

def check_cache_status(output_base_dir="outputs"):
    """检查缓存状态"""
    print("缓存状态检查")
    print("="*80)
    
    total_cached_files = 0
    total_cache_size = 0
    
    for image_type in ['user', 'hairstyle']:
        cache_dir = os.path.join(output_base_dir, f"gemini_processed_{image_type}")
        cache_index_path = os.path.join(cache_dir, "cache_index.json")
        
        print(f"\n📁 {image_type.upper()} 图片缓存状态:")
        print("-" * 60)
        
        if not os.path.exists(cache_dir):
            print(f"❌ 缓存目录不存在: {cache_dir}")
            continue
        
        if not os.path.exists(cache_index_path):
            print(f"❌ 缓存索引文件不存在: {cache_index_path}")
            continue
        
        try:
            # 读取缓存索引
            with open(cache_index_path, 'r', encoding='utf-8') as f:
                cache_index = json.load(f)
            
            if not cache_index:
                print(f"📝 缓存索引为空")
                continue
            
            print(f"📊 索引中记录的文件数: {len(cache_index)}")
            
            # 检查实际文件存在情况
            valid_files = 0
            invalid_files = 0
            type_cache_size = 0
            
            print(f"\n📋 缓存文件详情:")
            print(f"{'序号':<4} {'原始文件名':<30} {'状态':<6} {'大小':<10} {'时间':<20}")
            print("-" * 80)
            
            for i, (file_hash, info) in enumerate(cache_index.items(), 1):
                original_filename = info.get('original_filename', 'Unknown')
                processed_path = info.get('processed_path', '')
                timestamp = info.get('timestamp', '')
                
                # 格式化时间戳
                try:
                    if timestamp:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        time_str = dt.strftime('%m-%d %H:%M')
                    else:
                        time_str = 'Unknown'
                except:
                    time_str = 'Invalid'
                
                # 检查文件是否存在
                if os.path.exists(processed_path):
                    file_size = os.path.getsize(processed_path)
                    size_str = format_file_size(file_size)
                    status = "✅"
                    valid_files += 1
                    type_cache_size += file_size
                else:
                    size_str = "N/A"
                    status = "❌"
                    invalid_files += 1
                
                # 截断文件名如果太长
                display_name = original_filename[:28] + ".." if len(original_filename) > 30 else original_filename
                
                print(f"{i:<4} {display_name:<30} {status:<6} {size_str:<10} {time_str:<20}")
                
                # 只显示前10个文件的详情，避免输出太长
                if i >= 10:
                    remaining = len(cache_index) - 10
                    if remaining > 0:
                        print(f"... 还有 {remaining} 个文件 ...")
                    break
            
            print("-" * 80)
            print(f"📈 统计信息:")
            print(f"  有效缓存文件: {valid_files}")
            print(f"  无效缓存文件: {invalid_files}")
            print(f"  缓存总大小: {format_file_size(type_cache_size)}")
            
            total_cached_files += valid_files
            total_cache_size += type_cache_size
            
        except Exception as e:
            print(f"❌ 读取缓存索引失败: {e}")
    
    # 总体统计
    print("\n" + "="*80)
    print("📊 总体缓存统计:")
    print(f"  总缓存文件数: {total_cached_files}")
    print(f"  总缓存大小: {format_file_size(total_cache_size)}")
    print("="*80)
    
    return total_cached_files > 0

def check_directory_cache_coverage(base_directories, output_base_dir="outputs"):
    """检查目录的缓存覆盖情况"""
    print("\n🔍 缓存覆盖情况分析:")
    print("="*80)
    
    from batch_gemini_processor import BatchGeminiProcessor
    
    # 创建一个简化的处理器来使用其方法
    class SimpleCacheChecker:
        def __init__(self, output_base_dir):
            self.output_base_dir = output_base_dir
        
        def get_file_hash(self, file_path):
            import hashlib
            hash_md5 = hashlib.md5()
            try:
                with open(file_path, "rb") as f:
                    for chunk in iter(lambda: f.read(4096), b""):
                        hash_md5.update(chunk)
                return hash_md5.hexdigest()
            except:
                return None
        
        def determine_image_type(self, image_path):
            path_lower = image_path.lower()
            if '/user/' in path_lower or '\\user\\' in path_lower:
                return 'user'
            elif '/hairstyle/' in path_lower or '\\hairstyle\\' in path_lower:
                return 'hairstyle'
            elif '/hairstyle2/' in path_lower or '\\hairstyle2\\' in path_lower:
                return 'hairstyle'
            else:
                if 'user' in path_lower:
                    return 'user'
                elif 'hairstyle' in path_lower or 'hair' in path_lower:
                    return 'hairstyle'
                else:
                    if '/man/' in path_lower or '/woman/' in path_lower:
                        return 'hairstyle'
                    else:
                        return 'user'
        
        def find_image_files(self, directory):
            image_extensions = {'.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG'}
            image_files = []
            for root, dirs, files in os.walk(directory):
                for file in files:
                    if any(file.endswith(ext) for ext in image_extensions):
                        image_files.append(os.path.join(root, file))
            return image_files
        
        def get_cached_processed_path(self, original_path, image_type):
            try:
                file_hash = self.get_file_hash(original_path)
                if not file_hash:
                    return None
                
                cache_dir = os.path.join(self.output_base_dir, f"gemini_processed_{image_type}")
                cache_index_path = os.path.join(cache_dir, "cache_index.json")
                
                if not os.path.exists(cache_index_path):
                    return None
                
                try:
                    with open(cache_index_path, 'r', encoding='utf-8') as f:
                        cache_index = json.load(f)
                except:
                    return None
                
                if file_hash in cache_index:
                    cached_info = cache_index[file_hash]
                    cached_path = cached_info["processed_path"]
                    
                    if os.path.exists(cached_path):
                        return cached_path
                
                return None
            except:
                return None
    
    checker = SimpleCacheChecker(output_base_dir)
    
    for directory in base_directories:
        if not os.path.exists(directory):
            continue
        
        print(f"\n📂 目录: {directory}")
        image_files = checker.find_image_files(directory)
        
        if not image_files:
            print("  📝 未找到图片文件")
            continue
        
        # 统计缓存情况
        cached_count = {'user': 0, 'hairstyle': 0}
        total_count = {'user': 0, 'hairstyle': 0}
        
        for image_file in image_files:
            image_type = checker.determine_image_type(image_file)
            total_count[image_type] += 1
            
            cached_path = checker.get_cached_processed_path(image_file, image_type)
            if cached_path:
                cached_count[image_type] += 1
        
        print(f"  📊 统计:")
        for img_type in ['user', 'hairstyle']:
            total = total_count[img_type]
            cached = cached_count[img_type]
            if total > 0:
                percentage = (cached / total) * 100
                print(f"    {img_type}: {cached}/{total} ({percentage:.1f}%) 已缓存")

def main():
    """主函数"""
    output_base_dir = "outputs"
    
    # 检查基本缓存状态
    has_cache = check_cache_status(output_base_dir)
    
    if has_cache:
        # 如果有缓存，检查覆盖情况
        base_directories = [
            "/Users/alex_wu/work/hair/man",
            "/Users/alex_wu/work/hair/woman"
        ]
        check_directory_cache_coverage(base_directories, output_base_dir)
    else:
        print("\n💡 提示: 当前没有找到任何缓存文件")
        print("   运行 batch_gemini_processor.py 开始处理图片")

if __name__ == "__main__":
    main()
