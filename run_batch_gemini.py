#!/usr/bin/env python3
"""
运行批量Gemini图片预处理
简化的启动脚本
"""

import os
import sys

def check_dependencies():
    """检查依赖包"""
    try:
        from openai import AsyncOpenAI
        from PIL import Image
        from dotenv import load_dotenv
        return True
    except ImportError as e:
        print(f"缺少依赖包: {e}")
        print("请运行: pip install openai pillow python-dotenv")
        return False

def check_api_key():
    """检查API密钥"""
    from dotenv import load_dotenv
    load_dotenv()
    
    api_key = os.environ.get('OPENROUTER_API_KEY')
    if not api_key:
        print("错误: 未设置OPENROUTER_API_KEY环境变量")
        print("请在.env文件中设置: OPENROUTER_API_KEY=your_key_here")
        return False
    
    print(f"✓ API密钥已设置 (前8位: {api_key[:8]}...)")
    return True

def main():
    """主函数"""
    print("批量Gemini图片预处理启动器")
    print("="*50)
    
    # 检查依赖
    if not check_dependencies():
        sys.exit(1)
    
    # 检查API密钥
    if not check_api_key():
        sys.exit(1)
    
    # 导入并运行主处理器
    try:
        from batch_gemini_processor import BatchGeminiProcessor
        
        # 配置参数
        base_directories = [
            "/Users/alex_wu/work/hair/man",
            "/Users/alex_wu/work/hair/woman"
        ]
        
        max_workers = 5  # 可以根据需要调整
        output_dir = "outputs"
        
        print(f"配置信息:")
        print(f"  并发线程数: {max_workers}")
        print(f"  输出目录: {output_dir}")
        print(f"  处理目录: {len(base_directories)}个")
        for i, directory in enumerate(base_directories, 1):
            status = "✓" if os.path.exists(directory) else "✗"
            print(f"    {i}. {status} {directory}")
        
        # 询问是否继续
        response = input(f"\n是否开始处理? (y/N): ").strip().lower()
        if response not in ['y', 'yes', '是']:
            print("用户取消操作")
            return
        
        # 创建处理器
        processor = BatchGeminiProcessor(
            max_workers=max_workers, 
            output_base_dir=output_dir
        )
        
        # 处理每个目录
        for directory in base_directories:
            if os.path.exists(directory):
                print(f"\n{'='*60}")
                print(f"开始处理目录: {directory}")
                print(f"{'='*60}")
                processor.process_directory(directory)
            else:
                print(f"跳过不存在的目录: {directory}")
        
        print(f"\n{'='*60}")
        print("所有目录处理完成！")
        print(f"{'='*60}")
        
    except Exception as e:
        print(f"运行过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n用户中断处理")
    except Exception as e:
        print(f"启动器错误: {e}")
        sys.exit(1)
