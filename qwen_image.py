import json
import os
from dashscope import MultiModalConversation,ImageSynthesis
import base64
import mimetypes
import time
from http import HTTPStatus

# ---用于 Base64 编码 ---
# 格式为 data:{mime_type};base64,{base64_data}
def encode_file(file_path):
    # 检查文件是否存在
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"图像文件不存在: {file_path}")

    # 检查是否为文件（而不是目录）
    if not os.path.isfile(file_path):
        raise ValueError(f"路径不是文件: {file_path}")

    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type or not mime_type.startswith("image/"):
        raise ValueError("不支持或无法识别的图像格式")

    try:
        with open(file_path, "rb") as image_file:
            encoded_string = base64.b64encode(
                image_file.read()).decode('utf-8')
        return f"data:{mime_type};base64,{encoded_string}"
    except IOError as e:
        raise IOError(f"读取文件时出错: {file_path}, 错误: {str(e)}")


# 获取图像的 Base64 编码
# 调用编码函数，请将 "/path/to/your/image.png" 替换为您的本地图片文件路径，否则无法运行
image = encode_file("/Users/alex_wu/work/hair/man/hairstyle2/492e07e8-f64a-4cfb-8f11-166af2017bf8.jpeg")

# messages = [
#     {
#         "role": "user",
#         "content": [
#             {"image": image},
#             {"text": "保持人物一致性，保持服饰和发型不变，改为半身证件照，露出黑色腰带。4K HD"}
#         ]
#     }
# ]

# 若没有配置环境变量，请用百炼 API Key 将下行替换为：api_key="sk-xxx"
api_key = 'sk-5d14a5e2c3b244789903bb0a4343a7ba'

a = time.time()
def sample_sync_call_imageedit():
    print('please wait...')
    rsp = ImageSynthesis.call(api_key=api_key,
                              model="wanx2.1-imageedit",
                              function="expand",
                              prompt="改为半身证件照，露出黑色腰带。4K HD",
                              base_image_url=image,
                              n=1)
    assert rsp.status_code == HTTPStatus.OK

    print('response: %s' % rsp)
    if rsp.status_code == HTTPStatus.OK:
        for result in rsp.output.results:
            print("---------------------------")
            print(result.url)
    else:
        print('sync_call Failed, status_code: %s, code: %s, message: %s' %
              (rsp.status_code, rsp.code, rsp.message))
b=time.time()
print(f"Time taken: {b - a} seconds")

if __name__ == '__main__':
    sample_sync_call_imageedit()