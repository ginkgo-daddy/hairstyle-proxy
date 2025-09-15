import http.client
import json
import os
import requests
##本接口用于“图生图”流程中上传图片至 RunningHub 服务器。上传后的图片将被 LoadImage 节点加载，作为工作流中的输入图像使用。
import http.client
import mimetypes
from codecs import encode

conn = http.client.HTTPSConnection("www.runninghub.cn")
dataList = []
boundary = 'wL36Yn8afVp8Ag7AmP8qZ0SA4n1v9T'
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=apiKey;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode("b8ef5bbe2d9b46efa3311ce92cc68716"))
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=file; filename={0}'.format('D:\\temp\\ComfyUI_00743_uiqpt_1742470204.png')))

fileType = mimetypes.guess_type('D:\\temp\\ComfyUI_00743_uiqpt_1742470204.png')[0] or 'application/octet-stream'
dataList.append(encode('Content-Type: {}'.format(fileType)))
dataList.append(encode(''))

with open('D:\temp\ComfyUI_00743_uiqpt_1742470204.png', 'rb') as f:
   dataList.append(f.read())
dataList.append(encode('--' + boundary))
dataList.append(encode('Content-Disposition: form-data; name=fileType;'))

dataList.append(encode('Content-Type: {}'.format('text/plain')))
dataList.append(encode(''))

dataList.append(encode("image"))
dataList.append(encode('--'+boundary+'--'))
dataList.append(encode(''))
body = b'\r\n'.join(dataList)
payload = body
headers = {
   'Host': 'www.runninghub.cn',
   'Content-type': 'multipart/form-data; boundary={}'.format(boundary)
}
conn.request("POST", "/task/openapi/upload", payload, headers)
res = conn.getresponse()
data = res.read()
print(data.decode("utf-8"))
#返回结果：
# {
#     "code": 0,
#     "msg": "success",
#     "data": {
#         "fileName": "api/e9308c38644ccee4b95780f95f2db0d578c77a904a1648ca215c7fa7a8dd7d00.jpeg",
#         "fileType": "image"
#     }
# }
# 获取上传返回的 fileName 后，可在工作流配置中填入如下结构：
# "nodeInfoList": [
#   {
#     "nodeId": "10",
#     "fieldName": "image",
#     "fieldValue": "api/9d77b8530f8b3591edc5c4e8f3f55b2cf0960bb2ca35c04e32c1677687866576.png"
#   }
# ]
# nodeId：LoadImage 节点的编号
# fieldName：字段名，图像输入请使用 "image"
# fieldValue：上传返回的 fileName 字段值

## 发起AI应用任务
conn = http.client.HTTPSConnection("www.runninghub.cn")
payload = json.dumps({
   "webappId": 1967522806713946113,
   "apiKey": "b8ef5bbe2d9b46efa3311ce92cc68716",
   "nodeInfoList": [
        {
            "nodeId": "238",##发型参考照片
            "fieldName": "image",
            "fieldValue": "896bc7cafe4d8134e6015cddf2282c89f08ca2d3eb8b358083740d392fcdbf92.png", ##上传后返回的 fileName 
            "description": "hair"
        },
        {
            "nodeId": "239", ##用户照片
            "fieldName": "image",
            "fieldValue": "eeb68b4d6ba80fb58172abe8c3ad3cd4b7e8b537407b085e10b4b17c8308fe79.jpeg", ##上传后返回的 fileName 
            "description": "usr"
        }
    ]
})
headers = {
   'Host': 'www.runninghub.cn',
   'Content-Type': 'application/json'
}
conn.request("POST", "/task/openapi/ai-app/run", payload, headers)
res = conn.getresponse()
data = res.read()
print(data.decode("utf-8"))

## 返回状态说明：
# {
#     "code": 421,
#     "msg": "TASK_QUEUE_MAXED",
#     "data": null
# }
# 如果返回以上内容，则表示队列满了，需要等待队列空闲后，再发起任务
# {
#     "code": 0,
#     "msg": "success",
#     "data": {
#         "netWssUrl": null,
#         "taskId": "1955206193997234177",
#         "clientId": "780706e1e0d1a65106d437bd426deb12",
#         "taskStatus": "QUEUED",
#         "promptTips": "{\"result\": true, \"error\": null, \"outputs_to_execute\": [\"252\", \"100\", \"155\", \"226\"], \"node_errors\": {}}"
#     }
# }
# 如果返回以上内容，则表示正在队列中，可以根据taskId来查询任务状态

##查询任务状态
payload = json.dumps({
   "apiKey": "b8ef5bbe2d9b46efa3311ce92cc68716",
   "taskId": "1955206193997234177"
})
headers = {
   'Host': 'www.runninghub.cn',
   'Content-Type': 'application/json'
}
conn.request("POST", "/task/openapi/status", payload, headers)
res = conn.getresponse()
data = res.read()
print(data.decode("utf-8"))

## 返回状态说明：
# {
#     "code": 0,
#     "msg": "success",
#     "data": "SUCCESS"
# }
# 表示任务成功，可以去获取任务结果了

## 获取任务结果
payload = json.dumps({
   "apiKey": "b8ef5bbe2d9b46efa3311ce92cc68716",
   "taskId": "1955206193997234177"
})
headers = {
   'Host': 'www.runninghub.cn',
   'Content-Type': 'application/json'
}
conn.request("POST", "/task/openapi/outputs", payload, headers)
res = conn.getresponse()
data = res.read()
print(data.decode("utf-8"))
## 返回结果：
# {
#     "code": 0,
#     "msg": "success",
#     "data": [
#         {
#             "fileUrl": "https://rh-images.xiaoyaoyou.com/dc9274f9ee16b48f593e4386c4e20b8f/output/ComfyUI_00001_chopc_1754992521.png",
#             "fileType": "png",
#             "taskCostTime": "64",
#             "nodeId": "467"
#         },
#          {
#             "fileUrl": "https://rh-images.xiaoyaoyou.com/dc9274f9ee16b48f593e4386c4e20b8f/output/ComfyUI_00002_tnvsp_1757932543.png",
#             "fileType": "png",
#             "taskCostTime": "257",
#             "nodeId": "465"
#           },
#     ] //有可能生成多个图片，所以是list
# }
#可以通过fileUrl拿到新生成的照片