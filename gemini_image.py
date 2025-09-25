from email import message
from openai import OpenAI
import base64
import os
from datetime import datetime
import time

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


base64_image = encode_image("/Users/alex_wu/work/hair/man/hairstyle2/492e07e8-f64a-4cfb-8f11-166af2017bf8.jpeg")

client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  # base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
  api_key='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'
  # api_key='sk-5d14a5e2c3b244789903bb0a4343a7ba'
)
a = time.time()
completion = client.chat.completions.create(
  extra_headers={},
  extra_body={},
  model="google/gemini-2.5-flash-image-preview",
  messages=[
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "保持人物一致性，保持服饰和发型不变，改为半身证件照，露出黑色腰带。4K HD"
        },
        {
          "type": "image_url", # 
          "image_url": {
            "url": f"data:image/jpeg;base64,{base64_image}"
          }
        }
      ]
    }
  ]
)
b = time.time()
print(f"Time taken: {b - a} seconds")
# 从base64字符串中还原图片并保存
def save_image_from_base64(base64_str, output_dir="output_images"):
    """
    从base64字符串还原图片并保存到指定目录
    
    Args:
        base64_str: base64编码的图片字符串
        output_dir: 输出目录路径
    
    Returns:
        str: 保存的图片文件路径
    """
    try:
        # 创建输出目录（如果不存在）
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        # 生成唯一的文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"gemini_image_{timestamp}.png"
        filepath = os.path.join(output_dir, filename)
        
        # 解码base64并保存图片
        image_data = base64.b64decode(base64_str)
        with open(filepath, "wb") as f:
            f.write(image_data)
        
        print(f"图片已保存到: {filepath}")
        return filepath
        
    except Exception as e:
        print(f"保存图片时出错: {e}")
        return None

# 从API响应中提取base64图片数据并保存
if hasattr(completion.choices[0].message, 'images') and completion.choices[0].message.images:
    image_url = completion.choices[0].message.images[0]["image_url"]['url']
    
    # 提取base64部分（假设格式为 data:image/png;base64,{base64_string}）
    if image_url.startswith("data:image/"):
        base64_data = image_url.split(",")[1]
        saved_path = save_image_from_base64(base64_data)
        
        if saved_path:
            print(f"成功保存图片: {saved_path}")
        else:
            print("保存图片失败")
    else:
        print(f"非base64格式的图片URL: {image_url}")
else:
    print("API响应中没有找到图片数据")


