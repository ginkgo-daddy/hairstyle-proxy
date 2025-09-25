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
import sqlite3
import json

app = Flask(__name__)
CORS(app)

# 全局存储临时会话数据（生产环境建议用Redis）
sessions = {}

def ensure_data_directory():
    """确保数据目录存在并有适当的权限"""
    data_dir = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', '/data')
    try:
        if not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)
            print(f"创建数据目录: {data_dir}")
        
        # 检查目录权限
        if not os.access(data_dir, os.W_OK):
            print(f"警告: 数据目录 {data_dir} 没有写权限")
        else:
            print(f"数据目录就绪: {data_dir}")
            
        return data_dir
    except Exception as e:
        print(f"初始化数据目录失败: {e}")
        # 回退到当前目录
        fallback_dir = os.path.join(os.getcwd(), 'data')
        os.makedirs(fallback_dir, exist_ok=True)
        print(f"使用回退数据目录: {fallback_dir}")
        return fallback_dir

# 数据库初始化
def init_database():
    """初始化SQLite数据库"""
    data_dir = ensure_data_directory()

    db_path = os.path.join(data_dir, 'hairstyle_auth.db')
    print(f"数据库路径: {db_path}")
    print(f"数据目录是否存在: {os.path.exists(data_dir)}")
    print(f"数据库文件是否存在: {os.path.exists(db_path)}")
    print(f"RAILWAY_VOLUME_MOUNT_PATH环境变量: {os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', '未设置')}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 创建激活码表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activation_codes (
            code TEXT PRIMARY KEY,
            used BOOLEAN DEFAULT FALSE,
            subscription_type TEXT NOT NULL,
            duration_days INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            used_at TIMESTAMP NULL,
            used_by_device TEXT NULL
        )
    ''')

    # 创建设备表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            activation_code TEXT,
            subscription_type TEXT,
            activated_at TIMESTAMP,
            expires_at TIMESTAMP,
            last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (activation_code) REFERENCES activation_codes (code)
        )
    ''')

    conn.commit()

    # 检查是否有测试数据，如果没有则添加
    cursor.execute('SELECT COUNT(*) FROM activation_codes')
    count = cursor.fetchone()[0]

    if count == 0:
        test_codes = [
            ("HAIR-2024-DEMO-001", "premium", 365),
            ("HAIR-2024-DEMO-002", "premium", 365),
            ("HAIR-2024-DEMO-003", "premium", 365)
        ]
        for code, sub_type, days in test_codes:
            cursor.execute('''
                INSERT INTO activation_codes (code, subscription_type, duration_days)
                VALUES (?, ?, ?)
            ''', (code, sub_type, days))
        conn.commit()
        print(f"初始化了 {len(test_codes)} 个测试激活码到数据库")

    conn.close()

# 数据库操作函数
def get_db_connection():
    """获取数据库连接"""
    data_dir = ensure_data_directory()
    db_path = os.path.join(data_dir, 'hairstyle_auth.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # 使结果可以像字典一样访问
    return conn

def get_activation_code(code):
    """获取激活码信息"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM activation_codes WHERE code = ?', (code,))
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None

def get_device(device_id):
    """获取设备信息"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM devices WHERE device_id = ?', (device_id,))
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None

def create_activation_code_db(code, subscription_type, duration_days):
    """创建新的激活码到数据库"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO activation_codes (code, subscription_type, duration_days)
            VALUES (?, ?, ?)
        ''', (code, subscription_type, duration_days))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def activate_device_db(device_id, activation_code, subscription_type, expires_at):
    """激活设备到数据库"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 标记激活码为已使用
    cursor.execute('''
        UPDATE activation_codes
        SET used = TRUE, used_at = CURRENT_TIMESTAMP, used_by_device = ?
        WHERE code = ?
    ''', (device_id, activation_code))

    # 添加或更新设备记录
    cursor.execute('''
        INSERT OR REPLACE INTO devices
        (device_id, activation_code, subscription_type, activated_at, expires_at, last_check)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, CURRENT_TIMESTAMP)
    ''', (device_id, activation_code, subscription_type, expires_at))

    conn.commit()
    conn.close()

def update_device_last_check(device_id):
    """更新设备最后检查时间"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE devices SET last_check = CURRENT_TIMESTAMP WHERE device_id = ?
    ''', (device_id,))
    conn.commit()
    conn.close()

def get_all_activation_codes():
    """获取所有激活码"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM activation_codes ORDER BY created_at DESC
    ''')
    results = cursor.fetchall()
    conn.close()
    return [dict(row) for row in results]

def get_all_devices():
    """获取所有设备"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM devices ORDER BY activated_at DESC
    ''')
    results = cursor.fetchall()
    conn.close()
    return [dict(row) for row in results]

def delete_device(device_id):
    """删除设备并重置相关激活码状态"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 先获取设备信息
        cursor.execute('SELECT activation_code FROM devices WHERE device_id = ?', (device_id,))
        device = cursor.fetchone()

        if device:
            activation_code = device['activation_code']

            # 删除设备记录
            cursor.execute('DELETE FROM devices WHERE device_id = ?', (device_id,))

            # 重置激活码状态
            cursor.execute('''
                UPDATE activation_codes
                SET used = FALSE, used_at = NULL, used_by_device = NULL
                WHERE code = ?
            ''', (activation_code,))

            conn.commit()
            conn.close()
            return True
        else:
            conn.close()
            return False
    except Exception as e:
        conn.close()
        raise e

# 初始化数据库
init_database()

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
        # 获取数据目录并创建临时文件目录
        data_dir = ensure_data_directory()
        temp_dir = os.path.join(data_dir, 'temp_uploads')
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir, exist_ok=True)
        
        # 保存到临时文件
        temp_filename = f"{session_id}_{image_type}_{int(time.time() * 1000)}.jpg"
        temp_filepath = os.path.join(temp_dir, temp_filename)
        file.save(temp_filepath)

        # 创建图片访问URL，添加时间戳避免缓存
        base_url = request.url_root.rstrip('/')
        timestamp = int(time.time() * 1000)  # 使用毫秒时间戳
        image_url = f"{base_url}/api/image/{session_id}/{image_type}?t={timestamp}"

        with session_lock:
            sessions[session_id][f'{image_type}_image'] = temp_filepath
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
        
        # 额外清理：删除超过24小时的孤立临时文件
        try:
            data_dir = ensure_data_directory()
            temp_dir = os.path.join(data_dir, 'temp_uploads')
            if os.path.exists(temp_dir):
                for filename in os.listdir(temp_dir):
                    filepath = os.path.join(temp_dir, filename)
                    if os.path.isfile(filepath):
                        # 检查文件修改时间
                        file_mtime = os.path.getmtime(filepath)
                        if current_time - file_mtime > 24 * 3600:  # 超过24小时
                            try:
                                os.remove(filepath)
                                print(f"清理过期临时文件: {filename}")
                            except:
                                pass
        except Exception as e:
            print(f"清理临时文件目录失败: {e}")

# 授权验证相关API
@app.route('/api/device/activate', methods=['POST'])
def activate_device_api():
    """设备激活"""
    try:
        print("=== ACTIVATION REQUEST DEBUG ===")
        print(f"Method: {request.method}")
        print(f"Headers: {dict(request.headers)}")
        print(f"Content-Type: {request.content_type}")
        print(f"Raw data: {request.data}")

        data = request.get_json()
        print(f"Parsed JSON: {data}")

        device_id = data.get('device_id') if data else None
        activation_code = data.get('activation_code') if data else None

        print(f"Extracted - device_id: {device_id}, activation_code: {activation_code}")
        print("=== END DEBUG ===\n")

        if not device_id or not activation_code:
            return jsonify({'success': False, 'error': '设备ID和激活码不能为空'}), 400

        # 检查激活码是否存在
        code_info = get_activation_code(activation_code)
        if not code_info:
            return jsonify({'success': False, 'error': '激活码无效'}), 400

        # 先检查设备是否已激活（优先检查重新激活场景）
        device_info = get_device(device_id)
        print(f"Device lookup result: {device_info}")

        # 如果激活码已被使用，需要检查是否是同一设备重新激活
        if code_info['used']:
            print(f"Activation code {activation_code} is marked as used, checking device match...")
            if device_info and device_info['activation_code'] == activation_code:
                print(f"✓ SAME DEVICE REACTIVATION - 激活码被同一设备使用，允许重新激活")
                # 这是同一设备重新激活，继续处理重新激活逻辑
            else:
                print(f"✗ DIFFERENT DEVICE - 激活码被其他设备使用")
                return jsonify({'success': False, 'error': '激活码已被其他设备使用'}), 400

        if device_info:
            print(f"Device found - stored activation_code: '{device_info['activation_code']}', current request: '{activation_code}'")
            # 如果使用的是相同的激活码，允许重新激活（恢复激活状态）
            if device_info['activation_code'] == activation_code:
                print(f"✓ REACTIVATION MATCHED - 设备 {device_id} 使用相同激活码重新激活，返回现有激活信息")

                # 解析过期时间
                expires_at = datetime.datetime.fromisoformat(device_info['expires_at'].replace('Z', '+00:00'))
                if expires_at.tzinfo is not None:
                    expires_at = expires_at.replace(tzinfo=None)

                now = datetime.datetime.now()
                days_remaining = (expires_at - now).days

                return jsonify({
                    'success': True,
                    'message': '设备激活状态已恢复',
                    'subscription_type': device_info['subscription_type'],
                    'expires_at': device_info['expires_at'],
                    'days_remaining': max(0, days_remaining)
                })
            else:
                # 使用不同的激活码，提示错误
                expires_at = datetime.datetime.fromisoformat(device_info['expires_at'].replace('Z', '+00:00'))
                if expires_at.tzinfo is not None:
                    expires_at = expires_at.replace(tzinfo=None)

                now = datetime.datetime.now()
                days_remaining = (expires_at - now).days

                if days_remaining > 0:
                    error_msg = f"设备已使用其他激活码激活！当前订阅类型：{device_info['subscription_type']}，剩余 {days_remaining} 天。如需使用新激活码，请先在管理后台删除此设备。"
                else:
                    error_msg = f"设备已使用其他激活码激活但订阅已过期（过期 {-days_remaining} 天）。如需使用新激活码，请先在管理后台删除此设备。"

                return jsonify({
                    'success': False,
                    'error': error_msg,
                    'device_already_activated': True,
                    'current_subscription': device_info['subscription_type'],
                    'expires_at': device_info['expires_at'],
                    'days_remaining': days_remaining
                }), 400
        else:
            print(f"✓ NEW DEVICE - 设备 {device_id} 未找到记录，执行新设备激活")

        # 激活设备
        now = datetime.datetime.now()
        expire_date = now + timedelta(days=code_info['duration_days'])

        # 使用数据库函数激活设备
        activate_device_db(device_id, activation_code, code_info['subscription_type'], expire_date.isoformat())

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
        device_info = get_device(device_id)
        if not device_info:
            return jsonify({
                'success': False,
                'error': '设备未激活',
                'requires_activation': True
            }), 403

        now = datetime.datetime.now()

        # 更新最后检查时间
        update_device_last_check(device_id)

        # 解析expires_at字符串为datetime对象
        expires_at = datetime.datetime.fromisoformat(device_info['expires_at'].replace('Z', '+00:00'))
        if expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None)

        # 检查是否过期
        if now > expires_at:
            return jsonify({
                'success': False,
                'error': '订阅已过期',
                'requires_renewal': True,
                'expired_at': expires_at.isoformat()
            }), 403

        # 计算剩余天数
        days_remaining = (expires_at - now).days

        # 解析activated_at字符串为datetime对象
        activated_at = datetime.datetime.fromisoformat(device_info['activated_at'].replace('Z', '+00:00'))
        if activated_at.tzinfo is not None:
            activated_at = activated_at.replace(tzinfo=None)

        return jsonify({
            'success': True,
            'status': 'active',
            'subscription_type': device_info['subscription_type'],
            'expires_at': expires_at.isoformat(),
            'days_remaining': days_remaining,
            'activated_at': activated_at.isoformat()
        })

    except Exception as e:
        print(f"订阅检查失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/devices', methods=['GET'])
def list_devices():
    """管理员接口：查看所有设备"""
    devices_list = get_all_devices()
    device_list = []

    for device in devices_list:
        # 计算状态
        now = datetime.datetime.now()
        expires_at = datetime.datetime.fromisoformat(device['expires_at'].replace('Z', '+00:00'))
        if expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None)

        status = 'active' if now <= expires_at else 'expired'

        device_list.append({
            'device_id': device['device_id'],
            'subscription_type': device['subscription_type'],
            'status': status,
            'activated_at': device['activated_at'],
            'expires_at': device['expires_at'],
            'last_check': device['last_check'],
            'activation_code': device['activation_code']
        })

    return jsonify({
        'success': True,
        'devices': device_list,
        'total_count': len(device_list)
    })

@app.route('/api/admin/activation-codes', methods=['GET'])
def list_activation_codes():
    """管理员接口：查看所有激活码"""
    codes_list = get_all_activation_codes()

    return jsonify({
        'success': True,
        'activation_codes': codes_list,
        'total_count': len(codes_list)
    })

@app.route('/api/admin/delete-device/<device_id>', methods=['DELETE'])
def delete_device_api(device_id):
    """管理员接口：删除设备"""
    try:
        if delete_device(device_id):
            return jsonify({
                'success': True,
                'message': f'设备 {device_id} 已删除，激活码已重置'
            })
        else:
            return jsonify({
                'success': False,
                'error': '设备不存在'
            }), 404
    except Exception as e:
        print(f"删除设备失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

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
                if get_activation_code(custom_code):
                    return jsonify({'success': False, 'error': f'激活码 {custom_code} 已存在'}), 400
                activation_code = custom_code
            else:
                # 自动生成激活码
                activation_code = generate_activation_code(subscription_type, duration_days)

            # 确保激活码唯一
            while get_activation_code(activation_code):
                activation_code = generate_activation_code(subscription_type, duration_days)

            # 创建激活码到数据库
            if create_activation_code_db(activation_code, subscription_type, duration_days):
                created_codes.append(activation_code)
                print(f"创建激活码: {activation_code} ({subscription_type}, {duration_days}天)")
            else:
                return jsonify({'success': False, 'error': f'创建激活码失败: {activation_code}'}), 500

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

        .btn-danger {
            background: #dc3545;
        }

        .btn-danger:hover {
            background: #c82333;
        }

        .btn-sm {
            padding: 5px 10px;
            font-size: 12px;
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
                                <th>操作</th>
                            </tr>
                        </thead>
                        <tbody id="devicesTable">
                            <tr><td colspan="8" style="text-align: center;">加载中...</td></tr>
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
                            <td><code>${code.code}</code></td>
                            <td><span class="badge badge-${getTypeClass(code.subscription_type)}">${getTypeText(code.subscription_type)}</span></td>
                            <td>${code.duration_days} 天</td>
                            <td><span class="badge badge-${code.used ? 'danger' : 'success'}">${code.used ? '已使用' : '未使用'}</span></td>
                            <td>${formatDate(code.created_at)}</td>
                            <td>${code.used_at ? formatDate(code.used_at) : '-'}</td>
                            <td>${code.used_by_device || '-'}</td>
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
                        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center;">暂无设备</td></tr>';
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
                            <td>
                                <button class="btn btn-sm btn-danger" onclick="deleteDevice('${device.device_id}')"
                                    title="删除设备并重置激活码">🗑️ 删除</button>
                            </td>
                        </tr>
                    `).join('');
                }
            } catch (error) {
                console.error('加载设备失败:', error);
            }
        }

        // 删除设备
        async function deleteDevice(deviceId) {
            if (!confirm(`确定要删除设备 ${deviceId.substring(0, 12)}... 吗？\n\n这将会：\n- 删除设备记录\n- 重置相关激活码为可用状态\n\n此操作不可撤销！`)) {
                return;
            }

            try {
                const response = await fetch(`/api/admin/delete-device/${deviceId}`, {
                    method: 'DELETE'
                });
                const result = await response.json();

                if (result.success) {
                    alert(`✅ ${result.message}`);
                    loadStats();
                    loadActivationCodes();
                    loadDevices();
                } else {
                    alert(`❌ 删除失败: ${result.error}`);
                }
            } catch (error) {
                alert(`❌ 网络错误: ${error.message}`);
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