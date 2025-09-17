from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import tempfile
import os
import uuid
from hairstyle_processor_v2 import HairstyleProcessor
import threading
import time
import hashlib
import datetime
from datetime import timedelta

app = Flask(__name__)
CORS(app)

# 全局存储临时会话数据（生产环境建议用Redis）
sessions = {}

# 设备授权数据存储
devices = {}
activation_codes = {}

# 预设一些激活码用于测试
def init_activation_codes():
    test_codes = [
        "HAIR-2024-DEMO-001",
        "HAIR-2024-DEMO-002",
        "HAIR-2024-DEMO-003"
    ]
    for code in test_codes:
        activation_codes[code] = {
            'used': False,
            'subscription_type': 'premium',
            'duration_days': 365,
            'created_at': datetime.datetime.now()
        }
    print(f"初始化了 {len(test_codes)} 个测试激活码")

init_activation_codes()

# 初始化处理器，从环境变量获取API密钥
try:
    processor = HairstyleProcessor()
    print("HairstyleProcessor initialized successfully")
except ValueError as e:
    print(f"Warning: {e}")
    print("Please set RUNNINGHUB_API_KEY environment variable in Railway")
    processor = None

# 简单的内存存储锁
session_lock = threading.Lock()

@app.route('/')
def home():
    return jsonify({
        "message": "Hairstyle Proxy Server",
        "version": "1.0",
        "endpoints": {
            "create_session": "POST /api/create-session",
            "upload_page": "GET /upload/<session_id>/<image_type>",
            "upload_image": "POST /api/upload/<session_id>/<image_type>",
            "process_hairstyle": "POST /api/process/<session_id>",
            "get_session": "GET /api/session/<session_id>"
        }
    })

@app.route('/api/create-session', methods=['POST'])
def create_session():
    """创建新的上传会话"""
    session_id = str(uuid.uuid4())

    with session_lock:
        sessions[session_id] = {
            'user_image': None,
            'hairstyle_image': None,
            'user_image_url': None,
            'hairstyle_image_url': None,
            'status': 'created',
            'created_at': time.time()
        }

    # 生成二维码URL
    base_url = request.url_root.rstrip('/')
    user_qr_url = f"{base_url}/upload/{session_id}/user"
    hairstyle_qr_url = f"{base_url}/upload/{session_id}/hairstyle"

    return jsonify({
        'session_id': session_id,
        'user_upload_url': user_qr_url,
        'hairstyle_upload_url': hairstyle_qr_url,
        'status': 'created'
    })

@app.route('/upload/<session_id>/<image_type>')
def upload_page(session_id, image_type):
    """显示图片上传页面"""
    if session_id not in sessions:
        return "会话不存在", 404

    if image_type not in ['user', 'hairstyle']:
        return "图片类型错误", 400

    title = "用户照片" if image_type == 'user' else "发型参考图"

    html_template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>上传{{ title }}</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; text-align: center; background: #f5f5f5; }
            .container { max-width: 400px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h1 { color: #333; margin-bottom: 30px; }
            .upload-area { border: 2px dashed #ccc; padding: 40px; margin: 20px 0; border-radius: 10px; cursor: pointer; transition: all 0.3s; }
            .upload-area:hover { border-color: #007bff; background: #f8f9fa; }
            .upload-area.dragover { border-color: #007bff; background: #e3f2fd; }
            input[type="file"] { display: none; }
            .btn { background: #007bff; color: white; padding: 12px 30px; border: none; border-radius: 5px; font-size: 16px; cursor: pointer; margin: 10px; }
            .btn:hover { background: #0056b3; }
            .btn:disabled { background: #ccc; cursor: not-allowed; }
            .preview { max-width: 100%; max-height: 200px; margin: 10px 0; border-radius: 5px; }
            .status { margin: 10px 0; padding: 10px; border-radius: 5px; }
            .success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
            .error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
            .loading { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>上传{{ title }}</h1>

            <div class="upload-area" onclick="document.getElementById('fileInput').click()">
                <p>点击这里选择图片</p>
                <p>或拖拽图片到此区域</p>
                <small>支持 JPG, PNG 格式</small>
            </div>

            <input type="file" id="fileInput" accept="image/*">
            <div id="preview"></div>
            <button id="uploadBtn" class="btn" style="display: none;">上传图片</button>
            <div id="status"></div>
        </div>

        <script>
            const uploadArea = document.querySelector('.upload-area');
            const fileInput = document.getElementById('fileInput');
            const uploadBtn = document.getElementById('uploadBtn');
            const preview = document.getElementById('preview');
            const status = document.getElementById('status');
            let selectedFile = null;

            // 文件选择
            fileInput.addEventListener('change', handleFileSelect);

            // 拖拽上传
            uploadArea.addEventListener('dragover', (e) => {
                e.preventDefault();
                uploadArea.classList.add('dragover');
            });

            uploadArea.addEventListener('dragleave', () => {
                uploadArea.classList.remove('dragover');
            });

            uploadArea.addEventListener('drop', (e) => {
                e.preventDefault();
                uploadArea.classList.remove('dragover');
                const files = e.dataTransfer.files;
                if (files.length > 0) {
                    handleFile(files[0]);
                }
            });

            function handleFileSelect(e) {
                const file = e.target.files[0];
                if (file) handleFile(file);
            }

            function handleFile(file) {
                if (!file.type.startsWith('image/')) {
                    showStatus('请选择图片文件', 'error');
                    return;
                }

                selectedFile = file;

                // 预览图片
                const reader = new FileReader();
                reader.onload = (e) => {
                    preview.innerHTML = `<img src="${e.target.result}" class="preview" alt="预览">`;
                    uploadBtn.style.display = 'inline-block';
                };
                reader.readAsDataURL(file);
            }

            // 上传按钮
            uploadBtn.addEventListener('click', uploadFile);

            function uploadFile() {
                if (!selectedFile) return;

                showStatus('正在上传...', 'loading');
                uploadBtn.disabled = true;

                const formData = new FormData();
                formData.append('image', selectedFile);

                fetch(`/api/upload/{{ session_id }}/{{ image_type }}`, {
                    method: 'POST',
                    body: formData
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showStatus('上传成功！你可以关闭此页面。', 'success');
                        setTimeout(() => {
                            window.close();
                        }, 2000);
                    } else {
                        showStatus('上传失败：' + (data.error || '未知错误'), 'error');
                        uploadBtn.disabled = false;
                    }
                })
                .catch(error => {
                    showStatus('上传失败：网络错误', 'error');
                    uploadBtn.disabled = false;
                });
            }

            function showStatus(message, type) {
                status.innerHTML = `<div class="status ${type}">${message}</div>`;
            }
        </script>
    </body>
    </html>
    '''

    return render_template_string(html_template,
                                session_id=session_id,
                                image_type=image_type,
                                title=title)

@app.route('/api/upload/<session_id>/<image_type>', methods=['POST'])
def upload_image(session_id, image_type):
    """接收上传的图片"""
    if session_id not in sessions:
        return jsonify({'success': False, 'error': '会话不存在'}), 404

    if image_type not in ['user', 'hairstyle']:
        return jsonify({'success': False, 'error': '图片类型错误'}), 400

    if 'image' not in request.files:
        return jsonify({'success': False, 'error': '没有上传文件'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'error': '文件名为空'}), 400

    try:
        # 保存到临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
            file.save(tmp_file.name)

            # 创建图片访问URL，添加时间戳避免缓存
            base_url = request.url_root.rstrip('/')
            timestamp = int(time.time() * 1000)  # 使用毫秒时间戳
            image_url = f"{base_url}/api/image/{session_id}/{image_type}?t={timestamp}"

            with session_lock:
                sessions[session_id][f'{image_type}_image'] = tmp_file.name
                sessions[session_id][f'{image_type}_image_url'] = image_url

            return jsonify({
                'success': True,
                'message': '上传成功',
                'image_url': image_url
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/session/<session_id>')
def get_session(session_id):
    """获取会话状态"""
    if session_id not in sessions:
        return jsonify({'error': '会话不存在'}), 404

    session_data = sessions[session_id].copy()

    # 返回状态和图片URL
    return jsonify({
        'session_id': session_id,
        'has_user_image': session_data['user_image'] is not None,
        'has_hairstyle_image': session_data['hairstyle_image'] is not None,
        'user_image_url': session_data.get('user_image_url'),
        'hairstyle_image_url': session_data.get('hairstyle_image_url'),
        'status': session_data['status'],
        'ready_to_process': session_data['user_image'] is not None and session_data['hairstyle_image'] is not None
    })

@app.route('/api/process/<session_id>', methods=['POST'])
def process_hairstyle(session_id):
    """处理发型转换"""
    if session_id not in sessions:
        return jsonify({'success': False, 'error': '会话不存在'}), 404

    session_data = sessions[session_id]

    if not session_data['user_image'] or not session_data['hairstyle_image']:
        return jsonify({'success': False, 'error': '图片未完整上传'}), 400

    try:
        # 检查处理器是否正确初始化
        if processor is None:
            raise Exception("服务器配置错误：API密钥未设置")

        with session_lock:
            sessions[session_id]['status'] = 'processing'

        user_image_path = session_data['user_image']
        hairstyle_image_path = session_data['hairstyle_image']

        # 上传到RunningHub
        print(f"开始上传用户图片: {user_image_path}")
        user_filename = processor.upload_image(user_image_path)
        if not user_filename:
            raise Exception("用户图片上传失败")
        print(f"用户图片上传成功: {user_filename}")

        print(f"开始上传发型图片: {hairstyle_image_path}")
        hairstyle_filename = processor.upload_image(hairstyle_image_path)
        if not hairstyle_filename:
            raise Exception("发型图片上传失败")
        print(f"发型图片上传成功: {hairstyle_filename}")

        # 运行任务
        print(f"开始运行发型转换任务...")
        task_id = processor.run_hairstyle_task(hairstyle_filename, user_filename)
        if not task_id:
            raise Exception("任务启动失败")
        print(f"任务启动成功，任务ID: {task_id}")

        # 等待完成（最多10分钟）
        max_wait = 600
        wait_time = 0
        status = None

        while wait_time < max_wait:
            status = processor.check_task_status(task_id)
            if status == "SUCCESS":
                break
            elif status in ["FAILED", "CANCELLED"]:
                raise Exception(f"任务失败: {status}")
            elif status is None:
                raise Exception("状态检查失败")

            time.sleep(10)
            wait_time += 10

        if status != "SUCCESS":
            raise Exception("任务超时")

        # 获取结果
        results = processor.get_task_results(task_id)
        if not results:
            raise Exception("获取结果失败")

        # 提取图片URL
        result_urls = [result.get("fileUrl") for result in results if result.get("fileUrl")]

        with session_lock:
            sessions[session_id]['status'] = 'completed'

        return jsonify({
            'success': True,
            'result_urls': result_urls,
            'count': len(result_urls)
        })

    except Exception as e:
        with session_lock:
            sessions[session_id]['status'] = 'failed'

        return jsonify({'success': False, 'error': str(e)}), 500

    finally:
        # 清理临时文件
        # try:
        #     if session_data and session_data.get('user_image') and os.path.exists(session_data['user_image']):
        #         os.remove(session_data['user_image'])
        #     if session_data and session_data.get('hairstyle_image') and os.path.exists(session_data['hairstyle_image']):
        #         os.remove(session_data['hairstyle_image'])
        # except Exception as e:
        #     print(f"清理临时文件失败: {e}")
        pass

@app.route('/api/image/<session_id>/<image_type>')
def get_image(session_id, image_type):
    """获取上传的图片"""
    if session_id not in sessions:
        return "会话不存在", 404

    if image_type not in ['user', 'hairstyle']:
        return "图片类型错误", 400

    session_data = sessions[session_id]
    image_path = session_data.get(f'{image_type}_image')

    if not image_path or not os.path.exists(image_path):
        return "图片不存在", 404

    try:
        from flask import send_file
        return send_file(image_path, mimetype='image/jpeg')
    except Exception as e:
        return f"读取图片失败: {e}", 500

@app.route('/api/reset-image/<session_id>/<image_type>', methods=['POST'])
def reset_image(session_id, image_type):
    """重置指定类型的图片"""
    if session_id not in sessions:
        return jsonify({'success': False, 'error': '会话不存在'}), 404

    if image_type not in ['user', 'hairstyle']:
        return jsonify({'success': False, 'error': '图片类型错误'}), 400

    try:
        with session_lock:
            session_data = sessions[session_id]

            # 删除旧的临时文件
            old_image_path = session_data.get(f'{image_type}_image')
            if old_image_path and os.path.exists(old_image_path):
                try:
                    os.remove(old_image_path)
                except:
                    pass

            # 清除图片相关数据
            sessions[session_id][f'{image_type}_image'] = None
            sessions[session_id][f'{image_type}_image_url'] = None

        return jsonify({
            'success': True,
            'message': f'{image_type}图片已重置'
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# 清理过期会话的后台任务
def cleanup_expired_sessions():
    while True:
        time.sleep(3600)  # 每小时清理一次
        current_time = time.time()
        expired_sessions = []

        with session_lock:
            for session_id, session_data in sessions.items():
                if current_time - session_data['created_at'] > 24 * 3600:  # 24小时过期
                    expired_sessions.append(session_id)

        for session_id in expired_sessions:
            with session_lock:
                session_data = sessions.pop(session_id, {})

            # 清理临时文件
            try:
                if session_data.get('user_image') and os.path.exists(session_data['user_image']):
                    os.remove(session_data['user_image'])
                if session_data.get('hairstyle_image') and os.path.exists(session_data['hairstyle_image']):
                    os.remove(session_data['hairstyle_image'])
            except:
                pass

# 授权验证相关API
@app.route('/api/device/activate', methods=['POST'])
def activate_device():
    """设备激活"""
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        activation_code = data.get('activation_code')

        if not device_id or not activation_code:
            return jsonify({'success': False, 'error': '设备ID和激活码不能为空'}), 400

        # 检查激活码是否存在且未使用
        if activation_code not in activation_codes:
            return jsonify({'success': False, 'error': '激活码无效'}), 400

        code_info = activation_codes[activation_code]
        if code_info['used']:
            return jsonify({'success': False, 'error': '激活码已被使用'}), 400

        # 检查设备是否已激活
        if device_id in devices:
            return jsonify({'success': False, 'error': '设备已激活'}), 400

        # 激活设备
        now = datetime.datetime.now()
        expire_date = now + timedelta(days=code_info['duration_days'])

        devices[device_id] = {
            'activation_code': activation_code,
            'subscription_type': code_info['subscription_type'],
            'activated_at': now,
            'expires_at': expire_date,
            'status': 'active',
            'last_check': now
        }

        # 标记激活码已使用
        activation_codes[activation_code]['used'] = True
        activation_codes[activation_code]['used_at'] = now
        activation_codes[activation_code]['device_id'] = device_id

        print(f"设备 {device_id} 激活成功，过期时间: {expire_date}")

        return jsonify({
            'success': True,
            'message': '设备激活成功',
            'subscription_type': code_info['subscription_type'],
            'expires_at': expire_date.isoformat(),
            'days_remaining': code_info['duration_days']
        })

    except Exception as e:
        print(f"设备激活失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/device/check-subscription', methods=['POST'])
def check_subscription():
    """检查订阅状态"""
    try:
        data = request.get_json()
        device_id = data.get('device_id')

        if not device_id:
            return jsonify({'success': False, 'error': '设备ID不能为空'}), 400

        # 检查设备是否激活
        if device_id not in devices:
            return jsonify({
                'success': False,
                'error': '设备未激活',
                'requires_activation': True
            }), 403

        device_info = devices[device_id]
        now = datetime.datetime.now()

        # 更新最后检查时间
        devices[device_id]['last_check'] = now

        # 检查是否过期
        if now > device_info['expires_at']:
            devices[device_id]['status'] = 'expired'
            return jsonify({
                'success': False,
                'error': '订阅已过期',
                'requires_renewal': True,
                'expired_at': device_info['expires_at'].isoformat()
            }), 403

        # 计算剩余天数
        days_remaining = (device_info['expires_at'] - now).days

        return jsonify({
            'success': True,
            'status': 'active',
            'subscription_type': device_info['subscription_type'],
            'expires_at': device_info['expires_at'].isoformat(),
            'days_remaining': days_remaining,
            'activated_at': device_info['activated_at'].isoformat()
        })

    except Exception as e:
        print(f"订阅检查失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/devices', methods=['GET'])
def list_devices():
    """管理员接口：查看所有设备"""
    device_list = []
    for device_id, info in devices.items():
        device_list.append({
            'device_id': device_id,
            'subscription_type': info['subscription_type'],
            'status': info['status'],
            'activated_at': info['activated_at'].isoformat(),
            'expires_at': info['expires_at'].isoformat(),
            'last_check': info['last_check'].isoformat() if 'last_check' in info else None,
            'activation_code': info['activation_code']
        })

    return jsonify({
        'success': True,
        'devices': device_list,
        'total_count': len(device_list)
    })

@app.route('/api/admin/activation-codes', methods=['GET'])
def list_activation_codes():
    """管理员接口：查看所有激活码"""
    code_list = []
    for code, info in activation_codes.items():
        code_list.append({
            'activation_code': code,
            'used': info['used'],
            'subscription_type': info['subscription_type'],
            'duration_days': info['duration_days'],
            'created_at': info['created_at'].isoformat(),
            'used_at': info['used_at'].isoformat() if 'used_at' in info else None,
            'device_id': info.get('device_id', None)
        })

    return jsonify({
        'success': True,
        'activation_codes': code_list,
        'total_count': len(code_list)
    })

@app.route('/api/admin/create-activation-code', methods=['POST'])
def create_activation_code():
    """管理员接口：创建新的激活码"""
    try:
        data = request.get_json()

        # 参数验证
        subscription_type = data.get('subscription_type', 'premium')
        duration_days = data.get('duration_days', 365)
        custom_code = data.get('custom_code', None)
        quantity = data.get('quantity', 1)

        if subscription_type not in ['basic', 'pro', 'premium']:
            return jsonify({'success': False, 'error': '订阅类型无效'}), 400

        if duration_days <= 0 or duration_days > 3650:  # 最多10年
            return jsonify({'success': False, 'error': '有效期必须在1-3650天之间'}), 400

        if quantity <= 0 or quantity > 100:  # 一次最多创建100个
            return jsonify({'success': False, 'error': '数量必须在1-100之间'}), 400

        created_codes = []

        for i in range(quantity):
            if custom_code and quantity == 1:
                # 使用自定义激活码
                if custom_code in activation_codes:
                    return jsonify({'success': False, 'error': f'激活码 {custom_code} 已存在'}), 400
                activation_code = custom_code
            else:
                # 自动生成激活码
                activation_code = generate_activation_code(subscription_type, duration_days)

            # 确保激活码唯一
            while activation_code in activation_codes:
                activation_code = generate_activation_code(subscription_type, duration_days)

            # 创建激活码
            activation_codes[activation_code] = {
                'used': False,
                'subscription_type': subscription_type,
                'duration_days': duration_days,
                'created_at': datetime.datetime.now()
            }

            created_codes.append(activation_code)
            print(f"创建激活码: {activation_code} ({subscription_type}, {duration_days}天)")

        return jsonify({
            'success': True,
            'message': f'成功创建 {len(created_codes)} 个激活码',
            'activation_codes': created_codes,
            'subscription_type': subscription_type,
            'duration_days': duration_days
        })

    except Exception as e:
        print(f"创建激活码失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def generate_activation_code(subscription_type, duration_days):
    """生成激活码"""
    import random
    import string

    # 根据订阅类型设置前缀
    prefix_map = {
        'basic': 'HAIR-BASIC',
        'pro': 'HAIR-PRO',
        'premium': 'HAIR-PREM'
    }

    prefix = prefix_map.get(subscription_type, 'HAIR-UNKN')

    # 生成随机后缀
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

    return f"{prefix}-{suffix}"

# Web管理界面
@app.route('/admin')
def admin_dashboard():
    """管理员控制台首页"""
    return render_template_string(ADMIN_DASHBOARD_HTML)

# HTML模板
ADMIN_DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>发型应用管理控制台</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            color: #333;
        }

        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px 0;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }

        .container {
            max-width: 1200px;
            margin: 20px auto;
            padding: 0 20px;
        }

        .card {
            background: white;
            border-radius: 10px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            overflow: hidden;
        }

        .card-header {
            background: #f8f9fa;
            padding: 20px;
            border-bottom: 1px solid #eee;
            font-weight: bold;
            font-size: 18px;
        }

        .card-body {
            padding: 20px;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            border-left: 4px solid #667eea;
        }

        .stat-number {
            font-size: 24px;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 5px;
        }

        .stat-label {
            color: #666;
            font-size: 14px;
        }

        .form-group {
            margin-bottom: 15px;
        }

        .form-group label {
            display: block;
            margin-bottom: 5px;
            font-weight: 500;
        }

        .form-control {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
        }

        .form-control:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.1);
        }

        .btn {
            background: #667eea;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            transition: background 0.3s;
        }

        .btn:hover {
            background: #5a6fd8;
        }

        .btn-refresh {
            background: #28a745;
        }

        .btn-refresh:hover {
            background: #218838;
        }

        .table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }

        .table th, .table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }

        .table th {
            background: #f8f9fa;
            font-weight: 600;
        }

        .table tr:hover {
            background: #f8f9fa;
        }

        .badge {
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
        }

        .badge-success {
            background: #d4edda;
            color: #155724;
        }

        .badge-warning {
            background: #fff3cd;
            color: #856404;
        }

        .badge-danger {
            background: #f8d7da;
            color: #721c24;
        }

        .alert {
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 15px;
        }

        .alert-success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }

        .alert-danger {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }

        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }

        @media (max-width: 768px) {
            .form-row {
                grid-template-columns: 1fr;
            }

            .stats-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🎨 发型应用管理控制台</h1>
        <p>激活码与设备管理系统</p>
    </div>

    <div class="container">
        <!-- 统计信息 -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-number" id="totalCodes">-</div>
                <div class="stat-label">总激活码数</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" id="usedCodes">-</div>
                <div class="stat-label">已使用</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" id="activeDevices">-</div>
                <div class="stat-label">活跃设备</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" id="expiredDevices">-</div>
                <div class="stat-label">过期设备</div>
            </div>
        </div>

        <!-- 创建激活码 -->
        <div class="card">
            <div class="card-header">📝 创建新激活码</div>
            <div class="card-body">
                <div id="createAlert"></div>
                <form id="createForm">
                    <div class="form-row">
                        <div class="form-group">
                            <label for="subscriptionType">订阅类型</label>
                            <select id="subscriptionType" class="form-control">
                                <option value="premium">Premium (旗舰版)</option>
                                <option value="pro">Pro (专业版)</option>
                                <option value="basic">Basic (基础版)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="durationDays">有效期 (天)</label>
                            <input type="number" id="durationDays" class="form-control" value="365" min="1" max="3650">
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label for="quantity">创建数量</label>
                            <input type="number" id="quantity" class="form-control" value="1" min="1" max="100">
                        </div>
                        <div class="form-group">
                            <label for="customCode">自定义激活码 (可选)</label>
                            <input type="text" id="customCode" class="form-control" placeholder="留空自动生成">
                        </div>
                    </div>
                    <button type="submit" class="btn">🎯 创建激活码</button>
                </form>
            </div>
        </div>

        <!-- 激活码列表 -->
        <div class="card">
            <div class="card-header">
                📋 激活码管理
                <button class="btn btn-refresh" onclick="loadActivationCodes()" style="float: right;">🔄 刷新</button>
            </div>
            <div class="card-body">
                <div style="overflow-x: auto;">
                    <table class="table">
                        <thead>
                            <tr>
                                <th>激活码</th>
                                <th>类型</th>
                                <th>有效期</th>
                                <th>状态</th>
                                <th>创建时间</th>
                                <th>使用时间</th>
                                <th>设备ID</th>
                            </tr>
                        </thead>
                        <tbody id="activationCodesTable">
                            <tr><td colspan="7" style="text-align: center;">加载中...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- 设备列表 -->
        <div class="card">
            <div class="card-header">
                📱 设备管理
                <button class="btn btn-refresh" onclick="loadDevices()" style="float: right;">🔄 刷新</button>
            </div>
            <div class="card-body">
                <div style="overflow-x: auto;">
                    <table class="table">
                        <thead>
                            <tr>
                                <th>设备ID</th>
                                <th>订阅类型</th>
                                <th>状态</th>
                                <th>激活时间</th>
                                <th>过期时间</th>
                                <th>最后检查</th>
                                <th>激活码</th>
                            </tr>
                        </thead>
                        <tbody id="devicesTable">
                            <tr><td colspan="7" style="text-align: center;">加载中...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        // 页面加载时初始化
        document.addEventListener('DOMContentLoaded', function() {
            loadStats();
            loadActivationCodes();
            loadDevices();
        });

        // 创建激活码表单提交
        document.getElementById('createForm').addEventListener('submit', function(e) {
            e.preventDefault();
            createActivationCode();
        });

        // 创建激活码
        async function createActivationCode() {
            const formData = {
                subscription_type: document.getElementById('subscriptionType').value,
                duration_days: parseInt(document.getElementById('durationDays').value),
                quantity: parseInt(document.getElementById('quantity').value),
                custom_code: document.getElementById('customCode').value || undefined
            };

            try {
                const response = await fetch('/api/admin/create-activation-code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(formData)
                });

                const result = await response.json();

                if (result.success) {
                    showAlert('createAlert', 'success',
                        `✅ ${result.message}<br>创建的激活码：<br><strong>${result.activation_codes.join('<br>')}</strong>`);
                    document.getElementById('createForm').reset();
                    document.getElementById('durationDays').value = '365';
                    document.getElementById('quantity').value = '1';
                    loadStats();
                    loadActivationCodes();
                } else {
                    showAlert('createAlert', 'danger', `❌ ${result.error}`);
                }
            } catch (error) {
                showAlert('createAlert', 'danger', `❌ 网络错误: ${error.message}`);
            }
        }

        // 加载统计信息
        async function loadStats() {
            try {
                const [codesResponse, devicesResponse] = await Promise.all([
                    fetch('/api/admin/activation-codes'),
                    fetch('/api/admin/devices')
                ]);

                const codes = await codesResponse.json();
                const devices = await devicesResponse.json();

                if (codes.success && devices.success) {
                    const usedCodes = codes.activation_codes.filter(c => c.used).length;
                    const activeDevices = devices.devices.filter(d => d.status === 'active').length;
                    const expiredDevices = devices.devices.filter(d => d.status === 'expired').length;

                    document.getElementById('totalCodes').textContent = codes.total_count;
                    document.getElementById('usedCodes').textContent = usedCodes;
                    document.getElementById('activeDevices').textContent = activeDevices;
                    document.getElementById('expiredDevices').textContent = expiredDevices;
                }
            } catch (error) {
                console.error('加载统计信息失败:', error);
            }
        }

        // 加载激活码列表
        async function loadActivationCodes() {
            try {
                const response = await fetch('/api/admin/activation-codes');
                const result = await response.json();

                if (result.success) {
                    const tbody = document.getElementById('activationCodesTable');
                    if (result.activation_codes.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center;">暂无激活码</td></tr>';
                        return;
                    }

                    tbody.innerHTML = result.activation_codes.map(code => `
                        <tr>
                            <td><code>${code.activation_code}</code></td>
                            <td><span class="badge badge-${getTypeClass(code.subscription_type)}">${getTypeText(code.subscription_type)}</span></td>
                            <td>${code.duration_days} 天</td>
                            <td><span class="badge badge-${code.used ? 'danger' : 'success'}">${code.used ? '已使用' : '未使用'}</span></td>
                            <td>${formatDate(code.created_at)}</td>
                            <td>${code.used_at ? formatDate(code.used_at) : '-'}</td>
                            <td>${code.device_id || '-'}</td>
                        </tr>
                    `).join('');
                }
            } catch (error) {
                console.error('加载激活码失败:', error);
            }
        }

        // 加载设备列表
        async function loadDevices() {
            try {
                const response = await fetch('/api/admin/devices');
                const result = await response.json();

                if (result.success) {
                    const tbody = document.getElementById('devicesTable');
                    if (result.devices.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center;">暂无设备</td></tr>';
                        return;
                    }

                    tbody.innerHTML = result.devices.map(device => `
                        <tr>
                            <td><code>${device.device_id.substring(0, 12)}...</code></td>
                            <td><span class="badge badge-${getTypeClass(device.subscription_type)}">${getTypeText(device.subscription_type)}</span></td>
                            <td><span class="badge badge-${device.status === 'active' ? 'success' : 'danger'}">${device.status === 'active' ? '活跃' : '过期'}</span></td>
                            <td>${formatDate(device.activated_at)}</td>
                            <td>${formatDate(device.expires_at)}</td>
                            <td>${device.last_check ? formatDate(device.last_check) : '-'}</td>
                            <td><code>${device.activation_code}</code></td>
                        </tr>
                    `).join('');
                }
            } catch (error) {
                console.error('加载设备失败:', error);
            }
        }

        // 工具函数
        function showAlert(elementId, type, message) {
            const alertDiv = document.getElementById(elementId);
            alertDiv.innerHTML = `<div class="alert alert-${type}">${message}</div>`;
            setTimeout(() => alertDiv.innerHTML = '', 5000);
        }

        function formatDate(dateString) {
            return new Date(dateString).toLocaleString('zh-CN');
        }

        function getTypeClass(type) {
            const classes = { basic: 'warning', pro: 'success', premium: 'success' };
            return classes[type] || 'warning';
        }

        function getTypeText(type) {
            const texts = { basic: '基础版', pro: '专业版', premium: '旗舰版' };
            return texts[type] || type;
        }
    </script>
</body>
</html>
'''

# 启动清理线程
cleanup_thread = threading.Thread(target=cleanup_expired_sessions, daemon=True)
cleanup_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)