#!/usr/bin/env python3
"""
简单测试脚本 - 快速测试发型处理器的基本功能
集成OpenAI client调用Gemini进行图像预处理
"""

import os
import base64
import time
import asyncio
import hashlib
import json
from datetime import datetime
from openai import AsyncOpenAI
from hairstyle_processor_v2 import HairstyleProcessor
from dotenv import load_dotenv
load_dotenv()

def encode_image(image_path):
    """将图像编码为base64字符串，自动处理EXIF方向"""
    try:
        from PIL import Image, ExifTags
        import io

        # 使用PIL打开图像并自动处理EXIF方向
        with Image.open(image_path) as img:
            # 自动根据EXIF方向信息旋转图像
            img = fix_image_orientation(img)

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

def fix_image_orientation(img):
    """根据EXIF信息修正图像方向"""
    try:
        # 使用PIL的ImageOps.exif_transpose方法，这是处理EXIF方向的推荐方法
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
        return img
    except ImportError:
        # 如果ImageOps不可用，使用传统方法
        try:
            from PIL import ExifTags
            exif = img._getexif()
            if exif is not None:
                # 查找方向标签
                for tag, value in exif.items():
                    if ExifTags.TAGS.get(tag) == 'Orientation':
                        # 根据EXIF方向值旋转图像
                        if value == 2:
                            img = img.transpose(Image.FLIP_LEFT_RIGHT)
                        elif value == 3:
                            img = img.rotate(180, expand=True)
                        elif value == 4:
                            img = img.transpose(Image.FLIP_TOP_BOTTOM)
                        elif value == 5:
                            img = img.transpose(Image.FLIP_LEFT_RIGHT).rotate(90, expand=True)
                        elif value == 6:
                            img = img.rotate(-90, expand=True)
                        elif value == 7:
                            img = img.transpose(Image.FLIP_LEFT_RIGHT).rotate(-90, expand=True)
                        elif value == 8:
                            img = img.rotate(90, expand=True)
                        break
        except Exception as e:
            print(f"修正图像方向失败: {e}")

    return img

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

def save_image_from_base64(base64_str, original_path, image_type, file_hash):
    """从base64字符串还原图片并保存，使用哈希值命名"""
    try:
        output_dir = f"gemini_processed_{image_type}"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        # 使用文件哈希值作为主要标识符，保留原文件名用于识别
        original_filename = os.path.basename(original_path)
        name_without_ext = os.path.splitext(original_filename)[0]

        # 文件名格式: 原名_哈希前8位_gemini_processed.png
        new_filename = f"{name_without_ext}_{file_hash[:8]}_gemini_processed.png"
        filepath = os.path.join(output_dir, new_filename)

        # 解码base64并保存图片
        image_data = base64.b64decode(base64_str)
        with open(filepath, "wb") as f:
            f.write(image_data)

        # 更新缓存索引
        update_cache_index(original_path, filepath, file_hash, image_type)

        print(f"Gemini处理后的图片已保存到: {filepath}")
        return filepath

    except Exception as e:
        print(f"保存图片时出错: {e}")
        return None

def update_cache_index(original_path, processed_path, file_hash, image_type):
    """更新缓存索引文件"""
    try:
        cache_dir = f"gemini_processed_{image_type}"
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

def get_cached_processed_path(original_path, image_type):
    """基于文件哈希检查是否已有缓存的预处理图片"""
    try:
        # 计算原文件哈希
        file_hash = get_file_hash(original_path)
        if not file_hash:
            return None

        # 检查缓存索引
        cache_dir = f"gemini_processed_{image_type}"
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

async def preprocess_image_with_gemini(image_path, image_type="user"):
    """使用Gemini对图像进行预处理（异步版本）"""
    task_name = f"{image_type}_processor"
    try:
        print(f"[{task_name}] 开始使用Gemini处理{image_type}图像: {os.path.basename(image_path)}")

        # 检查缓存（基于文件哈希）
        cached_path = get_cached_processed_path(image_path, image_type)
        if cached_path:
            print(f"[{task_name}] ✓ 找到缓存的{image_type}图像: {os.path.basename(cached_path)}")
            return cached_path

        # 检查OpenRouter API密钥
        api_key = os.environ.get('OPENROUTER_API_KEY')
        if not api_key:
            print(f"[{task_name}] 警告: 未设置OPENROUTER_API_KEY，跳过Gemini预处理")
            return image_path

        # 计算文件哈希（用于保存时的文件命名）
        file_hash = get_file_hash(image_path)
        if not file_hash:
            print(f"[{task_name}] 无法计算文件哈希，跳过预处理")
            return image_path

        # 编码图像
        base64_image = encode_image(image_path)

        # 创建异步OpenAI客户端
        async with AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        ) as client:

            # 根据图片类型设置不同的提示语
            if image_type == "user":
                prompt_text = "保持人物一致性，保持服饰和发型不变，身材不要太胖，改为半身证件照，露出黑色腰带。"
            elif image_type == "hairstyle":
                prompt_text = "保持人物一致性，保持服饰和发型不变，改为半身证件照，露出黑色腰带。"
            else:
                prompt_text = "保持人物一致性，保持服饰和发型不变，改为半身证件照，露出黑色腰带。"

            # 异步调用Gemini模型
            start_time = time.time()
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
            print(f"[{task_name}] Gemini处理{image_type}图像耗时: {end_time - start_time:.2f} 秒")

            return await process_gemini_response(completion, image_path, image_type, file_hash, task_name, client, prompt_text, base64_image, attempt=1)

    except Exception as e:
        print(f"[{task_name}] Gemini预处理{image_type}图像出错: {e}")
        print(f"[{task_name}] 使用原图继续处理...")
        return image_path

async def process_gemini_response(completion, image_path, image_type, file_hash, task_name, client, prompt_text, base64_image, attempt=1):
    """处理Gemini API响应，包含重试机制"""
    max_retries = 2  # 最多重试1次，总共2次尝试

    # 检查响应中是否有图片数据
    if hasattr(completion.choices[0].message, 'images') and completion.choices[0].message.images:
        image_url = completion.choices[0].message.images[0]["image_url"]['url']

        # 提取base64部分
        if image_url.startswith("data:image/"):
            base64_data = image_url.split(",")[1]
            processed_image_path = save_image_from_base64(
                base64_data,
                image_path,    # 原始路径
                image_type,    # 图像类型
                file_hash      # 文件哈希
            )

            if processed_image_path:
                print(f"[{task_name}] ✓ Gemini{image_type}图像预处理成功: {os.path.basename(processed_image_path)}")
                return processed_image_path
            else:
                print(f"[{task_name}] 保存Gemini处理后的{image_type}图片失败，使用原图")
                return image_path
        else:
            print(f"[{task_name}] 非base64格式的图片URL: {image_url}")
            return image_path
    else:
        # 响应中无图片数据，尝试重试
        if attempt < max_retries:
            print(f"[{task_name}] 响应中无图片数据，进行第{attempt + 1}次尝试...")
            try:
                # 等待一小段时间再重试
                await asyncio.sleep(1)

                # 重新调用API
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

                print(f"[{task_name}] 重试请求完成，处理响应...")
                # 递归调用处理重试的响应
                return await process_gemini_response(
                    retry_completion, image_path, image_type, file_hash,
                    task_name, client, prompt_text, base64_image, attempt + 1
                )

            except Exception as retry_error:
                print(f"[{task_name}] 重试请求失败: {retry_error}")
                print(f"[{task_name}] 使用原图")
                return image_path
        else:
            print(f"[{task_name}] 达到最大重试次数，响应中仍无图片数据，使用原图")
            return image_path

async def process_images_concurrently(original_user_image, hairstyle_image):
    """并发处理两张图像"""
    print("开始并发处理用户图像和发型图像...")

    start_time = time.time()

    try:
        # 使用asyncio.gather并发执行两个异步任务
        print("✓ 两个异步预处理任务已启动，等待完成...")

        processed_user_image, processed_hairstyle_image = await asyncio.gather(
            preprocess_image_with_gemini(original_user_image, "user"),
            preprocess_image_with_gemini(hairstyle_image, "hairstyle"),
            return_exceptions=True  # 即使其中一个失败也继续
        )

        end_time = time.time()
        total_preprocessing_time = end_time - start_time

        # 处理可能的异常结果
        if isinstance(processed_user_image, Exception):
            print(f"✗ 用户图像预处理失败: {processed_user_image}")
            processed_user_image = original_user_image

        if isinstance(processed_hairstyle_image, Exception):
            print(f"✗ 发型图像预处理失败: {processed_hairstyle_image}")
            processed_hairstyle_image = hairstyle_image

        print(f"✓ Gemini并发预处理完成，总耗时: {total_preprocessing_time:.2f} 秒")
        return processed_user_image, processed_hairstyle_image

    except Exception as e:
        print(f"✗ 并发处理过程中发生错误: {e}")
        # 如果并发失败，使用原图
        return original_user_image, hairstyle_image

def main():
    print("=" * 60)
    print("发型处理器测试程序 (协程版Gemini图像预处理)")
    print("=" * 60)

    # 测试图片路径
    original_user_image = "/Users/alex_wu/work/hair/woman/user/WechatIMG307.jpeg"
    hairstyle_image = "/Users/alex_wu/work/hair/woman/hairstyle2/韩式外翻短发_1_胖迪阿乔_来自小红书网页版.jpg"

    # 检查文件是否存在
    if not os.path.exists(original_user_image):
        print(f"用户图片不存在: {original_user_image}")
        return

    if not os.path.exists(hairstyle_image):
        print(f"发型图片不存在: {hairstyle_image}")
        return

    print(f"原始用户图片: {original_user_image}")
    print(f"发型图片: {hairstyle_image}")

    # 检查环境变量
    runninghub_api_key = os.environ.get('RUNNINGHUB_API_KEY')
    runninghub_webapp_id = os.environ.get('RUNNINGHUB_WEBAPP_ID')
    openrouter_api_key = os.environ.get('OPENROUTER_API_KEY')

    if not runninghub_api_key:
        print("✗ 请设置环境变量 RUNNINGHUB_API_KEY")
        return

    if not runninghub_webapp_id:
        print("✗ 请设置环境变量 RUNNINGHUB_WEBAPP_ID")
        return

    print(f"✓ RunningHub API Key: {runninghub_api_key[:10]}...")
    print(f"✓ RunningHub Webapp ID: {runninghub_webapp_id}")

    if openrouter_api_key:
        print(f"✓ OpenRouter API Key: {openrouter_api_key[:10]}...")
    else:
        print("⚠ 未设置OpenRouter API Key，将跳过Gemini预处理")

    print("\n" + "=" * 60)
    print("步骤1&2: HairstyleProcessor (集成Gemini预处理 + RunningHub)")
    print("=" * 60)

    # 创建处理器
    try:
        processor = HairstyleProcessor(max_workers=1)
        print("✓ HairstyleProcessor 初始化成功")
    except Exception as e:
        print(f"✗ HairstyleProcessor 初始化失败: {e}")
        return

    # 创建结果目录
    results_dir = "simple_test_results"
    os.makedirs(results_dir, exist_ok=True)

    # 构造任务信息（使用原始图片，让HairstyleProcessor处理Gemini预处理）
    task_info = (
        original_user_image,      # user_full_path (原始用户图片)
        hairstyle_image,         # hairstyle_full_path (原始发型图片)
        "WechatIMG307.jpeg",     # user_file
        "韩式外翻短发_1_胖迪阿乔_来自小红书网页版.jpg",  # hairstyle_file
        "woman",                 # gender_name
        results_dir              # results_dir
    )

    print(f"使用原始用户图片: {original_user_image}")
    print(f"使用原始发型图片: {hairstyle_image}")
    print("开始完整处理流程 (Gemini预处理 + RunningHub发型转换)...")
    processor.process_single_combination(task_info)

    print("\n" + "=" * 60)
    print("处理完成 - 结果总览")
    print("=" * 60)

    print(f"结果保存在: {results_dir}")

    # 显示结果
    if os.path.exists(results_dir):
        files = os.listdir(results_dir)
        print(f"生成了 {len(files)} 个文件:")
        for file in files:
            file_path = os.path.join(results_dir, file)
            file_size = os.path.getsize(file_path) / 1024  # KB
            print(f"  - {file} ({file_size:.1f} KB)")

    # 显示Gemini预处理结果
    print("\nGemini预处理结果:")
    for image_type in ["user", "hairstyle"]:
        gemini_dir = f"gemini_processed_{image_type}"
        if os.path.exists(gemini_dir):
            gemini_files = os.listdir(gemini_dir)
            if gemini_files:
                print(f"  {image_type}图像预处理结果保存在: {gemini_dir}")
                for file in gemini_files:
                    file_path = os.path.join(gemini_dir, file)
                    file_size = os.path.getsize(file_path) / 1024  # KB
                    print(f"    - {file} ({file_size:.1f} KB)")
            else:
                print(f"  {image_type}图像: 未进行Gemini预处理")
        else:
            print(f"  {image_type}图像: 未进行Gemini预处理")

if __name__ == "__main__":
    # 运行主函数
    main()