#!/usr/bin/env python3
"""
批量Gemini图片预处理脚本
基于hairstyle_processor_v2.py中的preprocess_image_with_gemini函数
对指定目录下的所有图片进行Gemini预处理
"""

import os
import time
import asyncio
import threading
import concurrent.futures
from datetime import datetime
from pathlib import Path
import hashlib
import base64
import json
import io
from PIL import Image, ImageOps, ExifTags
from openai import AsyncOpenAI
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class BatchGeminiProcessor:
    def __init__(self, max_workers=5, output_base_dir="outputs"):
        # 从环境变量获取OpenRouter API密钥
        self.openrouter_api_key = os.environ.get('OPENROUTER_API_KEY')
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is required")
        
        self.max_workers = max_workers
        self.output_base_dir = output_base_dir
        
        # 统计信息
        self.processed_count = 0
        self.success_count = 0
        self.fail_count = 0
        self.cached_count = 0
        self.processing_times = []
        self.results_lock = threading.Lock()
        
        # 确保输出目录存在
        os.makedirs(output_base_dir, exist_ok=True)
        
        print(f"BatchGeminiProcessor initialized with {max_workers} workers")
        print(f"Output directory: {output_base_dir}")

    def get_file_hash(self, file_path):
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

    def encode_image(self, image_path):
        """将图像编码为base64字符串，自动处理EXIF方向"""
        try:
            with Image.open(image_path) as img:
                # 自动根据EXIF方向信息旋转图像
                img = ImageOps.exif_transpose(img)
                
                # 转换为RGB模式（避免PNG保存问题）
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # 保存到内存缓冲区
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=95)
                buffer.seek(0)
                
                # 编码为base64
                return base64.b64encode(buffer.getvalue()).decode('utf-8')
                
        except Exception as e:
            print(f"处理图像EXIF方向失败，使用原始方法: {e}")
            # 回退到原始方法
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')

    def determine_image_type(self, image_path):
        """根据路径确定图片类型"""
        path_lower = image_path.lower()
        
        # 检查路径中是否包含特定的文件夹名称
        if '/user/' in path_lower or '\\user\\' in path_lower:
            return 'user'
        elif '/hairstyle/' in path_lower or '\\hairstyle\\' in path_lower:
            return 'hairstyle'
        elif '/hairstyle2/' in path_lower or '\\hairstyle2\\' in path_lower:
            return 'hairstyle'
        else:
            # 如果路径中包含这些关键词，也进行判断
            if 'user' in path_lower:
                return 'user'
            elif 'hairstyle' in path_lower or 'hair' in path_lower:
                return 'hairstyle'
            else:
                # 默认根据目录结构判断
                if '/man/' in path_lower or '/woman/' in path_lower:
                    return 'hairstyle'  # 假设这些是发型图片
                else:
                    return 'user'

    def save_image_from_base64(self, base64_str, original_path, image_type, file_hash):
        """从base64字符串还原图片并保存"""
        try:
            output_dir = os.path.join(self.output_base_dir, f"gemini_processed_{image_type}")
            os.makedirs(output_dir, exist_ok=True)
            
            # 使用文件哈希值作为主要标识符
            original_filename = os.path.basename(original_path)
            name_without_ext = os.path.splitext(original_filename)[0]
            
            # 文件名格式: 原名_哈希前8位_gemini_processed.png
            new_filename = f"{name_without_ext}_{file_hash[:8]}_gemini_processed.png"
            filepath = os.path.join(output_dir, new_filename)
            
            image_data = base64.b64decode(base64_str)
            with open(filepath, "wb") as f:
                f.write(image_data)
            
            # 更新缓存索引
            self.update_cache_index(original_path, filepath, file_hash, image_type)
            
            return filepath
        except Exception as e:
            print(f"保存图片时出错: {e}")
            return None

    def update_cache_index(self, original_path, processed_path, file_hash, image_type):
        """更新缓存索引文件"""
        try:
            cache_dir = os.path.join(self.output_base_dir, f"gemini_processed_{image_type}")
            cache_index_path = os.path.join(cache_dir, "cache_index.json")
            
            # 读取现有索引
            cache_index = {}
            if os.path.exists(cache_index_path):
                try:
                    with open(cache_index_path, 'r', encoding='utf-8') as f:
                        cache_index = json.load(f)
                except:
                    cache_index = {}
            
            # 更新索引
            cache_index[file_hash] = {
                "original_path": original_path,
                "processed_path": processed_path,
                "timestamp": datetime.now().isoformat(),
                "original_filename": os.path.basename(original_path)
            }
            
            # 保存索引
            with open(cache_index_path, 'w', encoding='utf-8') as f:
                json.dump(cache_index, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            print(f"更新缓存索引失败: {e}")

    def get_cached_processed_path(self, original_path, image_type):
        """检查是否已有缓存的预处理图片"""
        try:
            # 计算原文件哈希
            file_hash = self.get_file_hash(original_path)
            if not file_hash:
                return None
            
            # 检查缓存索引
            cache_dir = os.path.join(self.output_base_dir, f"gemini_processed_{image_type}")
            cache_index_path = os.path.join(cache_dir, "cache_index.json")
            
            if not os.path.exists(cache_index_path):
                return None
            
            # 读取缓存索引
            try:
                with open(cache_index_path, 'r', encoding='utf-8') as f:
                    cache_index = json.load(f)
            except:
                return None
            
            # 查找匹配的哈希
            if file_hash in cache_index:
                cached_info = cache_index[file_hash]
                cached_path = cached_info["processed_path"]
                
                # 验证缓存文件是否仍然存在
                if os.path.exists(cached_path):
                    return cached_path
                else:
                    # 缓存文件不存在，清理索引
                    del cache_index[file_hash]
                    with open(cache_index_path, 'w', encoding='utf-8') as f:
                        json.dump(cache_index, f, ensure_ascii=False, indent=2)
            
            return None
            
        except Exception as e:
            print(f"检查缓存失败: {e}")
            return None

    async def preprocess_image_with_gemini(self, image_path, image_type=None):
        """使用Gemini对图像进行预处理"""
        thread_name = threading.current_thread().name
        start_time = time.time()
        
        try:
            if image_type is None:
                image_type = self.determine_image_type(image_path)
            
            print(f"[{thread_name}] 开始Gemini预处理{image_type}图像: {os.path.basename(image_path)}")
            
            # 检查缓存
            cached_path = self.get_cached_processed_path(image_path, image_type)
            if cached_path:
                print(f"[{thread_name}] ✓ 找到缓存的{image_type}图像: {os.path.basename(cached_path)}")
                with self.results_lock:
                    self.cached_count += 1
                return cached_path
            
            # 计算文件哈希
            file_hash = self.get_file_hash(image_path)
            if not file_hash:
                print(f"[{thread_name}] 无法计算文件哈希，跳过预处理")
                with self.results_lock:
                    self.fail_count += 1
                return image_path
            
            base64_image = self.encode_image(image_path)
            
            async with AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self.openrouter_api_key,
            ) as client:
                
                # 根据图片类型设置不同的提示语
                if image_type == "user":
                    prompt_text = "保持人物一致性，保持服饰和发型不变，身材不要太胖，改为半身证件照，光线充足，露出黑色腰带。"
                elif image_type == "hairstyle":
                    prompt_text = "保持人物一致性，保持服饰和发型发色不变，保持发型纹理清晰，光照条件与原图一致，改为半身证件照，露出黑色腰带。"
                else:
                    prompt_text = "保持人物一致性，保持服饰和发型发色不变，保持发型纹理清晰，光照条件与原图一致，改为半身证件照，露出黑色腰带。"
                
                completion = await client.chat.completions.create(
                    model="google/gemini-2.5-flash-image-preview",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": prompt_text
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{base64_image}"
                                    }
                                }
                            ]
                        }
                    ]
                )
                
                end_time = time.time()
                elapsed = end_time - start_time
                
                with self.results_lock:
                    self.processing_times.append(elapsed)
                
                print(f"[{thread_name}] Gemini预处理{image_type}耗时: {elapsed:.2f}秒")
                
                return await self.process_gemini_response(
                    completion, image_path, image_type, file_hash, 
                    thread_name, client, prompt_text, base64_image, attempt=1
                )
                
        except Exception as e:
            end_time = time.time()
            elapsed = end_time - start_time
            with self.results_lock:
                self.processing_times.append(elapsed)
                self.fail_count += 1
            print(f"[{thread_name}] Gemini预处理出错: {e}")
            print(f"[{thread_name}] 使用原图...")
            return image_path

    async def process_gemini_response(self, completion, image_path, image_type, file_hash, 
                                    thread_name, client, prompt_text, base64_image, attempt=1):
        """处理Gemini API响应"""
        max_retries = 2
        
        # 检查响应中是否有图片数据
        if hasattr(completion.choices[0].message, 'images') and completion.choices[0].message.images:
            image_url = completion.choices[0].message.images[0]["image_url"]['url']
            
            if image_url.startswith("data:image/"):
                base64_data = image_url.split(",")[1]
                processed_image_path = self.save_image_from_base64(
                    base64_data, image_path, image_type, file_hash
                )
                
                if processed_image_path:
                    print(f"[{thread_name}] ✓ Gemini{image_type}预处理成功: {os.path.basename(processed_image_path)}")
                    with self.results_lock:
                        self.success_count += 1
                    return processed_image_path
                else:
                    print(f"[{thread_name}] 保存失败，使用原图")
                    with self.results_lock:
                        self.fail_count += 1
                    return image_path
            else:
                print(f"[{thread_name}] 非base64格式URL，使用原图")
                with self.results_lock:
                    self.fail_count += 1
                return image_path
        else:
            # 响应中无图片数据，尝试重试
            if attempt < max_retries:
                print(f"[{thread_name}] 响应中无图片数据，进行第{attempt + 1}次尝试...")
                try:
                    await asyncio.sleep(1)
                    
                    retry_completion = await client.chat.completions.create(
                        model="google/gemini-2.5-flash-image-preview",
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": prompt_text
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{base64_image}"
                                        }
                                    }
                                ]
                            }
                        ]
                    )
                    
                    return await self.process_gemini_response(
                        retry_completion, image_path, image_type, file_hash,
                        thread_name, client, prompt_text, base64_image, attempt + 1
                    )
                    
                except Exception as retry_error:
                    print(f"[{thread_name}] 重试请求失败: {retry_error}")
                    with self.results_lock:
                        self.fail_count += 1
                    return image_path
            else:
                print(f"[{thread_name}] 达到最大重试次数，使用原图")
                with self.results_lock:
                    self.fail_count += 1
                return image_path

    def process_single_image_sync(self, image_path):
        """同步处理单个图片（用于线程池）"""
        try:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                result = loop.run_until_complete(
                    self.preprocess_image_with_gemini(image_path)
                )
                
                with self.results_lock:
                    self.processed_count += 1
                
                return result
            finally:
                loop.close()
                
        except Exception as e:
            print(f"处理图片失败 {image_path}: {e}")
            with self.results_lock:
                self.fail_count += 1
            return image_path

    def find_image_files(self, directory):
        """递归查找目录下的所有图片文件"""
        image_extensions = {'.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG'}
        image_files = []
        
        for root, dirs, files in os.walk(directory):
            for file in files:
                if any(file.endswith(ext) for ext in image_extensions):
                    image_files.append(os.path.join(root, file))
        
        return image_files

    def process_directory(self, directory):
        """处理目录下的所有图片"""
        if not os.path.exists(directory):
            print(f"目录不存在: {directory}")
            return
        
        print(f"开始扫描目录: {directory}")
        image_files = self.find_image_files(directory)
        
        if not image_files:
            print(f"在目录 {directory} 中未找到图片文件")
            return
        
        print(f"找到 {len(image_files)} 个图片文件")
        
        # 统计不同类型的图片数量
        type_counts = {'user': 0, 'hairstyle': 0}
        for image_file in image_files:
            image_type = self.determine_image_type(image_file)
            type_counts[image_type] += 1
        
        print(f"图片类型分布: user={type_counts['user']}, hairstyle={type_counts['hairstyle']}")
        print(f"开始使用 {self.max_workers} 个线程进行批量处理...")
        
        start_time = time.time()
        
        # 使用线程池并发处理
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_file = {
                executor.submit(self.process_single_image_sync, image_file): image_file 
                for image_file in image_files
            }
            
            # 处理完成的任务
            completed = 0
            for future in concurrent.futures.as_completed(future_to_file):
                completed += 1
                image_file = future_to_file[future]
                
                try:
                    result = future.result()
                    if completed % 10 == 0 or completed == len(image_files):
                        print(f"进度: {completed}/{len(image_files)} "
                              f"({completed/len(image_files)*100:.1f}%) - "
                              f"最新处理: {os.path.basename(image_file)}")
                except Exception as exc:
                    print(f'处理图片 {image_file} 时发生异常: {exc}')
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # 打印统计信息
        self.print_statistics(total_time)

    def print_statistics(self, total_time):
        """打印处理统计信息"""
        print("\n" + "="*60)
        print("批量Gemini预处理完成统计")
        print("="*60)
        print(f"总处理时间: {total_time:.2f}秒 ({total_time/60:.1f}分钟)")
        print(f"处理的图片总数: {self.processed_count}")
        print(f"成功预处理: {self.success_count}")
        print(f"使用缓存: {self.cached_count}")
        print(f"失败/跳过: {self.fail_count}")
        
        if self.success_count > 0:
            success_rate = (self.success_count / self.processed_count) * 100
            print(f"预处理成功率: {success_rate:.1f}%")
        
        if self.processing_times:
            avg_time = sum(self.processing_times) / len(self.processing_times)
            min_time = min(self.processing_times)
            max_time = max(self.processing_times)
            print(f"平均处理时间: {avg_time:.2f}秒")
            print(f"最快处理时间: {min_time:.2f}秒")
            print(f"最慢处理时间: {max_time:.2f}秒")
        
        if self.processed_count > 0:
            avg_throughput = self.processed_count / total_time
            print(f"平均吞吐量: {avg_throughput:.2f}张/秒")
        
        print("="*60)


def main():
    """主函数"""
    # 配置参数
    base_directories = [
        "/Users/alex_wu/work/hair/color"
        # "/Users/alex_wu/work/hair/man",
        # "/Users/alex_wu/work/hair/woman"
    ]
    
    max_workers = 3  # 并发线程数，可以根据API限制调整
    output_dir = "outputs"  # 输出目录
    
    try:
        # 创建处理器
        processor = BatchGeminiProcessor(
            max_workers=max_workers, 
            output_base_dir=output_dir
        )
        
        # 处理每个目录
        for directory in base_directories:
            if os.path.exists(directory):
                print(f"\n开始处理目录: {directory}")
                processor.process_directory(directory)
            else:
                print(f"目录不存在，跳过: {directory}")
        
        print("\n所有目录处理完成！")
        
    except ValueError as e:
        print(f"配置错误: {e}")
        print("请确保设置了OPENROUTER_API_KEY环境变量")
    except KeyboardInterrupt:
        print("\n用户中断处理")
    except Exception as e:
        print(f"处理过程中发生错误: {e}")


if __name__ == "__main__":
    main()
