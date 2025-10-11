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
            "get_session": "GET /api/session/<session_id>",
            "cancel_session": "POST /api/cancel-session/<session_id>",
            "cancel_task": "POST /task/openapi/cancel",
            "cache_info": "GET /api/admin/cache/info",
            "clean_cache": "POST /api/admin/cache/clean",
            "system_status": "GET /api/admin/system/status",
            "list_cache_files": "GET /api/admin/cache/files",
            "delete_cache_file": "DELETE /api/admin/cache/files/<image_type>/<filename>",
            "serve_cache_image": "GET /api/admin/cache/image/<image_type>/<filename>"
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
            'created_at': time.time(),
            'task_id': None,
            'cancel_requested': False
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

    # 返回状态和图片URL，以及处理结果
    response = {
        'session_id': session_id,
        'has_user_image': session_data['user_image'] is not None,
        'has_hairstyle_image': session_data['hairstyle_image'] is not None,
        'user_image_url': session_data.get('user_image_url'),
        'hairstyle_image_url': session_data.get('hairstyle_image_url'),
        'status': session_data['status'],
        'task_id': session_data.get('task_id'),
        'ready_to_process': session_data['user_image'] is not None and session_data['hairstyle_image'] is not None,
        'can_cancel': session_data.get('task_id') is not None and session_data['status'] == 'processing'
    }

    # 如果处理完成，返回结果URL
    if session_data['status'] == 'completed' and 'result_urls' in session_data:
        response['result_urls'] = session_data['result_urls']

    # 如果处理失败，返回错误信息
    if session_data['status'] == 'failed' and 'error' in session_data:
        response['error'] = session_data['error']

    return jsonify(response)

@app.route('/api/process/<session_id>', methods=['POST'])
def process_hairstyle(session_id):
    """启动发型转换处理（异步）"""
    if session_id not in sessions:
        return jsonify({'success': False, 'error': '会话不存在'}), 404

    session_data = sessions[session_id]

    if not session_data['user_image'] or not session_data['hairstyle_image']:
        return jsonify({'success': False, 'error': '图片未完整上传'}), 400

    # 检查处理器是否正确初始化
    if processor is None:
        return jsonify({'success': False, 'error': '服务器配置错误：API密钥未设置'}), 500

    # 检查是否已经在处理中
    if session_data.get('status') == 'processing':
        return jsonify({'success': False, 'error': '任务已在处理中'}), 400

    try:
        with session_lock:
            sessions[session_id]['status'] = 'processing'
            sessions[session_id]['cancel_requested'] = False

        # 启动后台处理线程
        processing_thread = threading.Thread(
            target=process_hairstyle_async,
            args=(session_id,),
            daemon=True
        )
        processing_thread.start()

        return jsonify({
            'success': True,
            'message': '处理任务已启动',
            'session_id': session_id,
            'status': 'processing'
        })

    except Exception as e:
        with session_lock:
            sessions[session_id]['status'] = 'failed'
        return jsonify({'success': False, 'error': str(e)}), 500


def process_hairstyle_async(session_id):
    """异步处理发型转换的后台函数"""
    try:
        session_data = sessions.get(session_id)
        if not session_data:
            return

        user_image_path = session_data['user_image']
        hairstyle_image_path = session_data['hairstyle_image']

        print(f"[{session_id}] 开始Gemini预处理图像...")
        # user_image_path, hairstyle_image_path = processor.preprocess_images_concurrently(
        #     user_image_path, hairstyle_image_path
        # )

        # 检查取消状态
        # if sessions.get(session_id, {}).get('cancel_requested', False):
        #     print(f"[{session_id}] 预处理完成后检测到取消请求")
        #     with session_lock:
        #         sessions[session_id]['status'] = 'cancelled'
        #     return

        # 上传到RunningHub
        print(f"[{session_id}] 开始上传用户图片: {user_image_path}")
        user_filename = processor.upload_image(user_image_path)
        if not user_filename:
            raise Exception("用户图片上传失败")
        print(f"[{session_id}] 用户图片上传成功: {user_filename}")

        # 检查取消状态
        if sessions.get(session_id, {}).get('cancel_requested', False):
            print(f"[{session_id}] 用户图片上传后检测到取消请求")
            with session_lock:
                sessions[session_id]['status'] = 'cancelled'
            return

        print(f"[{session_id}] 开始上传发型图片: {hairstyle_image_path}")
        hairstyle_filename = processor.upload_image(hairstyle_image_path)
        if not hairstyle_filename:
            raise Exception("发型图片上传失败")
        print(f"[{session_id}] 发型图片上传成功: {hairstyle_filename}")

        # 检查取消状态
        if sessions.get(session_id, {}).get('cancel_requested', False):
            print(f"[{session_id}] 发型图片上传后检测到取消请求")
            with session_lock:
                sessions[session_id]['status'] = 'cancelled'
            return

        # 定义取消检查函数
        def check_cancel():
            with session_lock:
                return sessions.get(session_id, {}).get('cancel_requested', False)

        # 运行任务
        print(f"[{session_id}] 开始运行发型转换任务...")
        task_id = processor.run_hairstyle_task(hairstyle_filename, user_filename, cancel_check_func=check_cancel)
        if not task_id:
            # 检查是否是因为取消导致的失败
            if check_cancel():
                with session_lock:
                    sessions[session_id]['status'] = 'cancelled'
                print(f"[{session_id}] 任务启动时检测到取消请求")
                return
            else:
                raise Exception("任务启动失败")
        print(f"[{session_id}] 任务启动成功，任务ID: {task_id}")

        # 保存task_id到session中
        with session_lock:
            sessions[session_id]['task_id'] = task_id

        # 等待完成（最多10分钟）
        max_wait = 600
        wait_time = 0
        status = None

        while wait_time < max_wait:
            # 检查取消状态
            if check_cancel():
                print(f"[{session_id}] 处理过程中检测到取消请求，尝试取消任务...")
                processor.cancel_task(task_id)
                with session_lock:
                    sessions[session_id]['status'] = 'cancelled'
                return

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
        print(f"[{session_id}] 任务ID: {task_id}完成,结果：{results}")

        # 提取图片URL
        result_urls = [result.get("fileUrl") for result in results if result.get("fileUrl")]

        with session_lock:
            sessions[session_id]['status'] = 'completed'
            sessions[session_id]['result_urls'] = result_urls

        print(f"[{session_id}] 任务处理完成，生成了 {len(result_urls)} 个结果")

    except Exception as e:
        print(f"[{session_id}] 异步处理失败: {e}")
        with session_lock:
            if sessions.get(session_id):
                sessions[session_id]['status'] = 'failed'
                sessions[session_id]['error'] = str(e)

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

@app.route('/api/process-color/<session_id>', methods=['POST'])
def process_color(session_id):
    """启动换发色处理（异步）"""
    if session_id not in sessions:
        return jsonify({'success': False, 'error': '会话不存在'}), 404

    session_data = sessions[session_id]

    if not session_data['user_image'] or not session_data['hairstyle_image']:
        return jsonify({'success': False, 'error': '图片未完整上传'}), 400

    # 检查处理器是否正确初始化
    if processor is None:
        return jsonify({'success': False, 'error': '服务器配置错误：API密钥未设置'}), 500

    # 检查换发色功能是否可用
    if not processor.color_webapp_id:
        return jsonify({'success': False, 'error': '换发色功能未配置'}), 500

    # 检查是否已经在处理中
    if session_data.get('status') == 'processing':
        return jsonify({'success': False, 'error': '任务已在处理中'}), 400

    try:
        with session_lock:
            sessions[session_id]['status'] = 'processing'
            sessions[session_id]['cancel_requested'] = False
            sessions[session_id]['task_type'] = 'color'  # 标记任务类型

        # 启动后台处理线程
        processing_thread = threading.Thread(
            target=process_color_async,
            args=(session_id,),
            daemon=True
        )
        processing_thread.start()

        return jsonify({
            'success': True,
            'message': '换发色任务已启动',
            'session_id': session_id,
            'status': 'processing'
        })

    except Exception as e:
        with session_lock:
            sessions[session_id]['status'] = 'failed'
        return jsonify({'success': False, 'error': str(e)}), 500


def process_color_async(session_id):
    """异步处理换发色的后台函数"""
    try:
        session_data = sessions.get(session_id)
        if not session_data:
            return

        user_image_path = session_data['user_image']
        hairstyle_image_path = session_data['hairstyle_image']

        print(f"[{session_id}] 开始换发色处理（不经过Gemini预处理）...")

        # 检查取消状态
        if sessions.get(session_id, {}).get('cancel_requested', False):
            print(f"[{session_id}] 处理开始前检测到取消请求")
            with session_lock:
                sessions[session_id]['status'] = 'cancelled'
            return

        # 直接上传原图到RunningHub（不经过Gemini预处理）
        print(f"[{session_id}] 开始上传用户图片: {user_image_path}")
        user_filename = processor.upload_image(user_image_path)
        if not user_filename:
            raise Exception("用户图片上传失败")
        print(f"[{session_id}] 用户图片上传成功: {user_filename}")

        # 检查取消状态
        if sessions.get(session_id, {}).get('cancel_requested', False):
            print(f"[{session_id}] 用户图片上传后检测到取消请求")
            with session_lock:
                sessions[session_id]['status'] = 'cancelled'
            return

        print(f"[{session_id}] 开始上传发型图片: {hairstyle_image_path}")
        color_filename = processor.upload_image(hairstyle_image_path)
        if not color_filename:
            raise Exception("发型图片上传失败")
        print(f"[{session_id}] 发型图片上传成功: {color_filename}")

        # 检查取消状态
        if sessions.get(session_id, {}).get('cancel_requested', False):
            print(f"[{session_id}] 发型图片上传后检测到取消请求")
            with session_lock:
                sessions[session_id]['status'] = 'cancelled'
            return

        # 定义取消检查函数
        def check_cancel():
            with session_lock:
                return sessions.get(session_id, {}).get('cancel_requested', False)

        # Step 1.5: 对发色参考图调用RunningHub预处理
        # print(f"[{session_id}] 开始发色预处理...")
        # preprocess_results = processor.call_runninghub_color_preprocess(color_filename)

        # # 使用预处理结果作为发色参考图
        processed_color_filename = color_filename  # 默认使用原图

        # if preprocess_results and len(preprocess_results) > 0:
        #     print(f"[{session_id}] 发色预处理成功，得到 {len(preprocess_results)} 个结果")
        #     # 保存第一个预处理结果
        #     first_result = preprocess_results[0]
        #     if first_result.get("fileUrl"):
        #         # 下载预处理结果到临时文件
        #         import requests
        #         data_dir = ensure_data_directory()
        #         temp_dir = os.path.join(data_dir, 'temp_uploads')
        #         preprocess_temp_path = os.path.join(temp_dir, f"{session_id}_color_preprocess_{int(time.time() * 1000)}.png")

        #         try:
        #             response = requests.get(first_result["fileUrl"])
        #             if response.status_code == 200:
        #                 with open(preprocess_temp_path, 'wb') as f:
        #                     f.write(response.content)
        #                 print(f"[{session_id}] 下载预处理结果成功: {preprocess_temp_path}")

        #                 # 重新上传预处理后的图片
        #                 processed_color_filename = processor.upload_image(preprocess_temp_path)
        #                 if processed_color_filename:
        #                     print(f"[{session_id}] 预处理图片上传成功: {processed_color_filename}")
        #                 else:
        #                     print(f"[{session_id}] 预处理图片上传失败，使用原图")
        #                     processed_color_filename = color_filename
        #             else:
        #                 print(f"[{session_id}] 下载预处理结果失败，使用原图")
        #         except Exception as e:
        #             print(f"[{session_id}] 处理预处理结果失败: {e}，使用原图")
        # else:
        #     print(f"[{session_id}] 发色预处理失败或无结果，使用原图")

        # # 检查取消状态
        # if sessions.get(session_id, {}).get('cancel_requested', False):
        #     print(f"[{session_id}] 发色预处理后检测到取消请求")
        #     with session_lock:
        #         sessions[session_id]['status'] = 'cancelled'
        #     return
        # 运行换发色任务（使用预处理后的发色图）
        print(f"[{session_id}] 开始运行换发色任务...")
        task_id = processor.run_color_task(processed_color_filename, user_filename, cancel_check_func=check_cancel)
        if not task_id:
            # 检查是否是因为取消导致的失败
            if check_cancel():
                with session_lock:
                    sessions[session_id]['status'] = 'cancelled'
                print(f"[{session_id}] 换发色任务启动时检测到取消请求")
                return
            else:
                raise Exception("换发色任务启动失败")
        print(f"[{session_id}] 换发色任务启动成功，任务ID: {task_id}")

        # 保存task_id到session中
        with session_lock:
            sessions[session_id]['task_id'] = task_id

        # 等待完成（最多10分钟）
        max_wait = 600
        wait_time = 0
        status = None

        while wait_time < max_wait:
            # 检查取消状态
            if check_cancel():
                print(f"[{session_id}] 换发色处理过程中检测到取消请求，尝试取消任务...")
                processor.cancel_task(task_id)
                with session_lock:
                    sessions[session_id]['status'] = 'cancelled'
                return

            status = processor.check_task_status(task_id)
            if status == "SUCCESS":
                break
            elif status in ["FAILED", "CANCELLED"]:
                raise Exception(f"换发色任务失败: {status}")
            elif status is None:
                raise Exception("状态检查失败")

            time.sleep(10)
            wait_time += 10

        if status != "SUCCESS":
            raise Exception(f"换发色任务未成功完成: {status}")

        # 获取结果
        print(f"[{session_id}] 获取换发色结果...")
        results = processor.get_task_results(task_id)
        if not results:
            raise Exception("获取换发色结果失败")

        # 保存结果图片并获取下载URL
        result_urls = []
        for i, result in enumerate(results):
            result_url = result.get("fileUrl")
            if result_url:
                result_urls.append(result_url)

        # 更新session状态
        with session_lock:
            sessions[session_id]['status'] = 'completed'
            sessions[session_id]['result_urls'] = result_urls
            sessions[session_id]['task_type'] = 'color'

        print(f"[{session_id}] 换发色处理完成，生成了 {len(result_urls)} 张结果图片")

    except Exception as e:
        print(f"[{session_id}] 换发色处理失败: {e}")
        with session_lock:
            if session_id in sessions:
                sessions[session_id]['status'] = 'failed'
                sessions[session_id]['error'] = str(e)

@app.route('/api/cancel-session/<session_id>', methods=['POST'])
def cancel_session_task(session_id):
    """基于session_id取消任务"""
    try:
        # 检查session是否存在
        if session_id not in sessions:
            return jsonify({
                'success': False,
                'error': '会话不存在'
            }), 404

        session_data = sessions[session_id]
        task_id = session_data.get('task_id')
        current_status = session_data.get('status')

        # 检查处理器是否正确初始化
        if processor is None:
            return jsonify({
                'success': False,
                'error': '服务器配置错误：API密钥未设置'
            }), 500

        # 设置取消标志
        with session_lock:
            sessions[session_id]['cancel_requested'] = True
            sessions[session_id]['status'] = 'cancelled'

        # 如果有task_id，尝试取消远程任务
        if task_id:
            print(f"收到基于Session的取消任务请求 - SessionID: {session_id}, TaskID: {task_id}")
            success = cancel_task_on_server(task_id)

            return jsonify({
                'success': True,
                'message': '任务取消成功' if success else '任务取消请求已发送（远程取消可能失败）',
                'session_id': session_id,
                'task_id': task_id,
                'cancelled_stage': 'remote_task'
            })
        else:
            # 没有task_id，可能正在排队或刚开始处理
            print(f"收到基于Session的取消请求 - SessionID: {session_id}, 状态: {current_status} (排队阶段)")

            return jsonify({
                'success': True,
                'message': '排队任务取消成功',
                'session_id': session_id,
                'cancelled_stage': 'queuing'
            })

    except Exception as e:
        print(f"基于Session取消任务失败: {e}")
        return jsonify({
            'success': False,
            'error': f'服务器内部错误: {str(e)}'
        }), 500

@app.route('/task/openapi/cancel', methods=['POST'])
def cancel_task():
    """取消任务的API接口"""
    try:
        data = request.get_json()

        # 验证请求参数
        if not data:
            return jsonify({
                'code': 1,
                'msg': '请求参数不能为空',
                'data': None
            }), 400

        task_id = data.get('taskId')

        # 参数验证
        if not task_id:
            return jsonify({
                'code': 1,
                'msg': 'taskId不能为空',
                'data': None
            }), 400

        # 检查处理器是否正确初始化
        if processor is None:
            return jsonify({
                'code': 1,
                'msg': '服务器配置错误：API密钥未设置',
                'data': None
            }), 500

        # 记录取消请求信息
        print(f"收到取消任务请求 - TaskID: {task_id}")

        # 调用取消任务方法（使用服务器环境变量中的API密钥）
        success = cancel_task_on_server(task_id)

        if success:
            return jsonify({
                'code': 0,
                'msg': '任务取消成功',
                'data': {
                    'taskId': task_id,
                    'status': 'cancelled'
                }
            })
        else:
            return jsonify({
                'code': 1,
                'msg': '任务取消失败或任务不存在',
                'data': None
            }), 400

    except Exception as e:
        print(f"取消任务失败: {e}")
        return jsonify({
            'code': 1,
            'msg': f'服务器内部错误: {str(e)}',
            'data': None
        }), 500

def cancel_task_on_server(task_id):
    """在服务器上取消任务的具体实现"""
    try:
        if processor is None:
            print("处理器未初始化")
            return False

        # 调用HairstyleProcessor的取消任务方法
        return processor.cancel_task(task_id)

    except Exception as e:
        print(f"取消任务时发生错误: {e}")
        return False

# 清理过期会话的后台任务
def cleanup_expired_sessions():
    while True:
        time.sleep(3600*24*3)  # 每三天清理一次
        current_time = time.time()
        expired_sessions = []

        with session_lock:
            for session_id, session_data in sessions.items():
                if current_time - session_data['created_at'] > 24 * 3600 * 3:  # 三天过期
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

        # 额外清理：删除超过三天过期的孤立临时文件
        try:
            data_dir = ensure_data_directory()
            temp_dir = os.path.join(data_dir, 'temp_uploads')
            if os.path.exists(temp_dir):
                for filename in os.listdir(temp_dir):
                    filepath = os.path.join(temp_dir, filename)
                    if os.path.isfile(filepath):
                        # 检查文件修改时间
                        file_mtime = os.path.getmtime(filepath)
                        if current_time - file_mtime > 24 * 3600 * 3:  #  三天过期
                            try:
                                os.remove(filepath)
                                print(f"清理过期临时文件: {filename}")
                            except:
                                pass
        except Exception as e:
            print(f"清理临时文件目录失败: {e}")

# Gemini缓存清理后台任务
def cleanup_gemini_cache():
    """定期清理Gemini缓存文件的后台任务"""
    while True:
        time.sleep(24 * 3600)  # 每24小时清理一次

        try:
            if processor is not None:
                print("开始定期清理Gemini缓存...")

                # 获取磁盘使用情况
                disk_usage = processor.get_disk_usage()
                if disk_usage:
                    usage_percent = disk_usage['usage_percent']
                    free_mb = disk_usage['free'] / (1024 * 1024)
                    total_mb = disk_usage['total'] / (1024 * 1024)

                    # 计算推荐的缓存大小限制 (磁盘总空间的90%)
                    recommended_cache_size_mb = int(total_mb * 0.9)

                    print(f"当前磁盘使用率: {usage_percent:.1f}%, 剩余空间: {free_mb:.1f}MB")
                    print(f"推荐缓存大小限制: {recommended_cache_size_mb}MB (磁盘90%)")

                    # 如果磁盘使用率超过85%或剩余空间少于50MB，进行更激进的清理
                    if usage_percent > 85 or free_mb < 50:
                        print("磁盘空间不足，进行激进清理...")
                        # 激进清理：6小时，缓存限制为磁盘空间的50%
                        aggressive_cache_limit = int(total_mb * 0.5)
                        cleanup_result = processor.clean_old_cache(max_age_hours=6, max_total_size_mb=aggressive_cache_limit)
                    else:
                        # 正常清理：删除超过24小时的文件，总缓存大小限制为磁盘空间的90%
                        cleanup_result = processor.clean_old_cache(max_age_hours=24, max_total_size_mb=recommended_cache_size_mb)

                    if cleanup_result['cleaned_files'] > 0:
                        print(f"Gemini缓存清理完成: 删除了{cleanup_result['cleaned_files']}个文件，释放{cleanup_result['cleaned_size'] / (1024*1024):.1f}MB空间")
                else:
                    # 如果无法获取磁盘信息，使用默认清理策略
                    cleanup_result = processor.clean_old_cache(max_age_hours=24, max_total_size_mb=100)

        except Exception as e:
            print(f"定期清理Gemini缓存失败: {e}")

        # 每次清理后等待6小时

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

# 缓存管理API接口
@app.route('/api/admin/cache/info', methods=['GET'])
def get_cache_info():
    """获取缓存信息"""
    try:
        if processor is None:
            return jsonify({'success': False, 'error': '处理器未初始化'}), 500

        cache_info = processor.get_cache_info()
        disk_usage = processor.get_disk_usage()

        total_cache_files = cache_info['user']['total_files'] + cache_info['hairstyle']['total_files']
        total_cache_size = cache_info['user']['total_size'] + cache_info['hairstyle']['total_size']

        response = {
            'success': True,
            'cache_summary': {
                'total_files': total_cache_files,
                'total_size': total_cache_size,
                'total_size_mb': total_cache_size / (1024 * 1024)
            },
            'cache_details': cache_info,
            'disk_usage': disk_usage
        }

        return jsonify(response)

    except Exception as e:
        print(f"获取缓存信息失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/cache/clean', methods=['POST'])
def clean_cache():
    """手动清理缓存"""
    try:
        if processor is None:
            return jsonify({'success': False, 'error': '处理器未初始化'}), 500

        data = request.get_json() or {}
        max_age_hours = data.get('max_age_hours', 24)
        max_total_size_mb = data.get('max_total_size_mb', 100)

        # 获取磁盘信息来计算推荐的缓存大小限制
        disk_usage = processor.get_disk_usage()
        max_allowed_cache_mb = 1000  # 默认最大值
        if disk_usage:
            # 磁盘总空间的90%作为缓存大小上限
            max_allowed_cache_mb = int((disk_usage['total'] * 0.9) / (1024 * 1024))

        # 参数验证
        if max_age_hours <= 0 or max_age_hours > 168:  # 最多7天
            return jsonify({'success': False, 'error': '时间范围必须在1-168小时之间'}), 400

        if max_total_size_mb <= 0:
            return jsonify({'success': False, 'error': '缓存大小限制必须大于0MB'}), 400

        if max_total_size_mb > max_allowed_cache_mb:
            return jsonify({'success': False, 'error': f'缓存大小限制不能超过{max_allowed_cache_mb}MB (磁盘空间90%)'}), 400

        # 执行清理
        cleanup_result = processor.clean_old_cache(
            max_age_hours=max_age_hours,
            max_total_size_mb=max_total_size_mb
        )

        return jsonify({
            'success': True,
            'message': '缓存清理完成',
            'cleaned_files': cleanup_result['cleaned_files'],
            'cleaned_size': cleanup_result['cleaned_size'],
            'cleaned_size_mb': cleanup_result['cleaned_size'] / (1024 * 1024)
        })

    except Exception as e:
        print(f"手动清理缓存失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/system/status', methods=['GET'])
def get_system_status():
    """获取系统状态"""
    try:
        response = {
            'success': True,
            'processor_initialized': processor is not None,
            'active_sessions': len(sessions),
            'timestamp': datetime.datetime.now().isoformat()
        }

        if processor is not None:
            # 获取缓存信息
            cache_info = processor.get_cache_info()
            total_cache_files = cache_info['user']['total_files'] + cache_info['hairstyle']['total_files']
            total_cache_size = cache_info['user']['total_size'] + cache_info['hairstyle']['total_size']

            # 获取磁盘使用情况
            disk_usage = processor.get_disk_usage()

            response.update({
                'cache_files': total_cache_files,
                'cache_size_mb': total_cache_size / (1024 * 1024),
                'disk_usage': disk_usage,
                'gemini_stats': {
                    'success_count': processor.gemini_success_count,
                    'fail_count': processor.gemini_fail_count,
                    'total_requests': len(processor.gemini_times)
                }
            })

        return jsonify(response)

    except Exception as e:
        print(f"获取系统状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/cache/files', methods=['GET'])
def list_cache_files():
    """获取缓存文件列表"""
    try:
        if processor is None:
            return jsonify({'success': False, 'error': '处理器未初始化'}), 500

        cache_files = processor.get_cache_files_detailed()

        return jsonify({
            'success': True,
            'cache_files': cache_files,
            'summary': {
                'user_files': len(cache_files['user']),
                'hairstyle_files': len(cache_files['hairstyle']),
                'total_files': len(cache_files['user']) + len(cache_files['hairstyle']),
                'user_size_mb': sum(f['size_mb'] for f in cache_files['user']),
                'hairstyle_size_mb': sum(f['size_mb'] for f in cache_files['hairstyle']),
                'total_size_mb': sum(f['size_mb'] for f in cache_files['user']) + sum(f['size_mb'] for f in cache_files['hairstyle'])
            }
        })

    except Exception as e:
        print(f"获取缓存文件列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/cache/files/<image_type>/<path:filename>', methods=['DELETE'])
def delete_cache_file(image_type, filename):
    """删除指定的缓存文件"""
    try:
        if processor is None:
            return jsonify({'success': False, 'error': '处理器未初始化'}), 500

        if image_type not in ['user', 'hairstyle']:
            return jsonify({'success': False, 'error': '图片类型无效'}), 400

        # 构建完整文件路径
        cache_dir = os.path.join(processor.data_dir, f"gemini_processed_{image_type}")
        file_path = os.path.join(cache_dir, filename)

        # 安全检查：确保文件名不包含路径遍历
        if '..' in filename or '/' in filename or '\\' in filename:
            return jsonify({'success': False, 'error': '无效的文件名'}), 400

        # 删除文件
        success = processor.delete_cache_file(file_path, image_type)

        if success:
            return jsonify({
                'success': True,
                'message': f'文件 {filename} 删除成功'
            })
        else:
            return jsonify({'success': False, 'error': '删除文件失败'}), 500

    except Exception as e:
        print(f"删除缓存文件失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/cache/image/<image_type>/<path:filename>')
def serve_cache_image(image_type, filename):
    """安全地提供缓存图片文件访问"""
    try:
        if processor is None:
            return "处理器未初始化", 500

        if image_type not in ['user', 'hairstyle']:
            return "图片类型无效", 400

        # 安全检查：确保文件名不包含路径遍历
        if '..' in filename or '/' in filename or '\\' in filename:
            return "无效的文件名", 400

        # 构建完整文件路径
        cache_dir = os.path.join(processor.data_dir, f"gemini_processed_{image_type}")
        file_path = os.path.join(cache_dir, filename)

        # 验证文件路径是否在缓存目录内（安全检查）
        normalized_file_path = os.path.normpath(file_path)
        normalized_cache_dir = os.path.normpath(cache_dir)

        if not normalized_file_path.startswith(normalized_cache_dir):
            return "文件路径不在缓存目录内", 403

        # 检查文件是否存在
        if not os.path.exists(file_path):
            return "图片不存在", 404

        try:
            from flask import send_file
            return send_file(file_path, mimetype='image/png')
        except Exception as e:
            return f"读取图片失败: {e}", 500

    except Exception as e:
        print(f"提供缓存图片失败: {e}")
        return f"服务器内部错误: {str(e)}", 500

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
            <div class="stat-card">
                <div class="stat-number" id="diskUsage">-</div>
                <div class="stat-label">磁盘使用率</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" id="cacheSize">-</div>
                <div class="stat-label">缓存大小</div>
            </div>
        </div>

        <!-- 系统状态和缓存管理 -->
        <div class="card">
            <div class="card-header">💾 系统状态与缓存管理</div>
            <div class="card-body">
                <div id="systemAlert"></div>
                <div class="form-row" style="margin-bottom: 20px;">
                    <div class="form-group">
                        <label>磁盘使用情况</label>
                        <div id="diskInfo" style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin-top: 5px;">
                            <div>总空间: <span id="diskTotal">加载中...</span></div>
                            <div>已使用: <span id="diskUsed">加载中...</span></div>
                            <div>剩余空间: <span id="diskFree">加载中...</span></div>
                            <div style="margin-top: 10px;">
                                <div style="background: #e9ecef; height: 20px; border-radius: 10px; overflow: hidden;">
                                    <div id="diskUsageBar" style="background: #28a745; height: 100%; width: 0%; transition: all 0.3s;"></div>
                                </div>
                                <div style="text-align: center; margin-top: 5px;">
                                    <span id="diskUsagePercent">0%</span> 已使用
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>缓存信息</label>
                        <div id="cacheInfo" style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin-top: 5px;">
                            <div>缓存文件数: <span id="cacheFileCount">加载中...</span></div>
                            <div>缓存总大小: <span id="cacheTotalSize">加载中...</span></div>
                            <div>用户图片缓存: <span id="userCacheSize">加载中...</span></div>
                            <div>发型图片缓存: <span id="hairstyleCacheSize">加载中...</span></div>
                        </div>
                    </div>
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label for="maxAgeHours">清理时间范围 (小时)</label>
                        <input type="number" id="maxAgeHours" class="form-control" value="24" min="1" max="168">
                        <small>删除超过指定小时数的缓存文件</small>
                    </div>
                    <div class="form-group">
                        <label for="maxSizeMB">缓存大小限制 (MB)</label>
                        <input type="number" id="maxSizeMB" class="form-control" value="100" min="10" max="1000">
                        <small>超过此大小时删除最旧的文件 (建议: <span id="recommendedSize">计算中...</span>)</small>
                    </div>
                </div>

                <div style="text-align: center; margin-top: 20px;">
                    <button class="btn btn-refresh" onclick="loadSystemInfo()" style="margin-right: 10px;">🔄 刷新状态</button>
                    <button class="btn" onclick="cleanCache()" id="cleanCacheBtn">🧹 立即清理缓存</button>
                </div>
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

        <!-- 缓存文件管理 -->
        <div class="card">
            <div class="card-header">
                📁 缓存文件管理
                <button class="btn btn-refresh" onclick="loadCacheFiles()" style="float: right;">🔄 刷新</button>
            </div>
            <div class="card-body">
                <div id="cacheFilesAlert"></div>

                <!-- 缓存文件统计 -->
                <div style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
                    <div class="form-row">
                        <div class="form-group">
                            <strong>用户图片缓存</strong>
                            <div>文件数: <span id="userCacheFileCount">-</span></div>
                            <div>大小: <span id="userCacheFileSize">-</span></div>
                        </div>
                        <div class="form-group">
                            <strong>发型图片缓存</strong>
                            <div>文件数: <span id="hairstyleCacheFileCount">-</span></div>
                            <div>大小: <span id="hairstyleCacheFileSize">-</span></div>
                        </div>
                    </div>
                </div>

                <!-- 文件列表切换 -->
                <div style="margin-bottom: 15px;">
                    <button class="btn" id="showUserFiles" onclick="showCacheFileType('user')">👤 用户图片缓存</button>
                    <button class="btn" id="showHairstyleFiles" onclick="showCacheFileType('hairstyle')" style="margin-left: 10px;">💇 发型图片缓存</button>
                </div>

                <!-- 用户图片缓存文件表格 -->
                <div id="userCacheFilesSection" style="display: none;">
                    <h4>用户图片缓存文件</h4>
                    <div style="overflow-x: auto;">
                        <table class="table">
                            <thead>
                                <tr>
                                    <th>预览</th>
                                    <th>文件名</th>
                                    <th>原始文件名</th>
                                    <th>大小</th>
                                    <th>修改时间</th>
                                    <th>操作</th>
                                </tr>
                            </thead>
                            <tbody id="userCacheFilesTable">
                                <tr><td colspan="6" style="text-align: center;">加载中...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- 发型图片缓存文件表格 -->
                <div id="hairstyleCacheFilesSection" style="display: none;">
                    <h4>发型图片缓存文件</h4>
                    <div style="overflow-x: auto;">
                        <table class="table">
                            <thead>
                                <tr>
                                    <th>预览</th>
                                    <th>文件名</th>
                                    <th>原始文件名</th>
                                    <th>大小</th>
                                    <th>修改时间</th>
                                    <th>操作</th>
                                </tr>
                            </thead>
                            <tbody id="hairstyleCacheFilesTable">
                                <tr><td colspan="6" style="text-align: center;">加载中...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- 图片预览模态对话框 -->
    <div id="imageModal" style="display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; overflow: auto; background-color: rgba(0,0,0,0.9);">
        <div style="position: relative; margin: auto; padding: 0; width: 90%; max-width: 800px; margin-top: 50px;">
            <!-- 关闭按钮 -->
            <span onclick="closeImageModal()" style="position: absolute; top: -35px; right: 0; color: #f1f1f1; font-size: 40px; font-weight: bold; cursor: pointer;">&times;</span>

            <!-- 图片内容 -->
            <img id="modalImage" style="width: 100%; height: auto; max-height: 80vh; object-fit: contain; border-radius: 10px;">

            <!-- 图片信息 -->
            <div style="background: rgba(255,255,255,0.9); padding: 15px; margin-top: 10px; border-radius: 5px; color: #333;">
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px;">
                    <div><strong>文件名:</strong> <span id="modalFileName">-</span></div>
                    <div><strong>原始文件名:</strong> <span id="modalOriginalFileName">-</span></div>
                    <div><strong>文件大小:</strong> <span id="modalFileSize">-</span></div>
                    <div><strong>修改时间:</strong> <span id="modalModifiedTime">-</span></div>
                    <div><strong>图片类型:</strong> <span id="modalImageType">-</span></div>
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
            loadSystemInfo();
            loadCacheFiles();
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

        // 加载系统信息
        async function loadSystemInfo() {
            try {
                const response = await fetch('/api/admin/system/status');
                const result = await response.json();

                if (result.success) {
                    // 更新磁盘使用情况
                    if (result.disk_usage) {
                        const diskUsage = result.disk_usage;
                        const totalGB = (diskUsage.total / (1024 * 1024 * 1024)).toFixed(1);
                        const usedGB = (diskUsage.used / (1024 * 1024 * 1024)).toFixed(1);
                        const freeGB = (diskUsage.free / (1024 * 1024 * 1024)).toFixed(1);
                        const usagePercent = diskUsage.usage_percent.toFixed(1);

                        document.getElementById('diskTotal').textContent = totalGB + ' GB';
                        document.getElementById('diskUsed').textContent = usedGB + ' GB';
                        document.getElementById('diskFree').textContent = freeGB + ' GB';
                        document.getElementById('diskUsagePercent').textContent = usagePercent + '%';

                        // 更新进度条
                        const progressBar = document.getElementById('diskUsageBar');
                        progressBar.style.width = usagePercent + '%';

                        // 根据使用率改变颜色
                        if (usagePercent > 90) {
                            progressBar.style.background = '#dc3545';
                        } else if (usagePercent > 80) {
                            progressBar.style.background = '#ffc107';
                        } else {
                            progressBar.style.background = '#28a745';
                        }

                        // 更新统计卡片
                        document.getElementById('diskUsage').textContent = usagePercent + '%';

                        // 计算并设置推荐的缓存大小限制 (磁盘总空间的90%)
                        const recommendedCacheSizeMB = Math.floor((diskUsage.total * 0.9) / (1024 * 1024));
                        document.getElementById('recommendedSize').textContent = recommendedCacheSizeMB + 'MB (磁盘90%)';

                        // 更新缓存大小限制输入框的最大值和默认值
                        const maxSizeMBInput = document.getElementById('maxSizeMB');
                        maxSizeMBInput.max = recommendedCacheSizeMB;

                        // 如果当前值超过推荐值或者是默认值100，则设置为推荐值
                        const currentValue = parseInt(maxSizeMBInput.value);
                        if (currentValue > recommendedCacheSizeMB || currentValue === 100) {
                            maxSizeMBInput.value = recommendedCacheSizeMB;
                        }
                    }

                    // 更新缓存信息
                    const cacheFiles = result.cache_files || 0;
                    const cacheSizeMB = result.cache_size_mb || 0;

                    document.getElementById('cacheFileCount').textContent = cacheFiles;
                    document.getElementById('cacheTotalSize').textContent = cacheSizeMB.toFixed(1) + ' MB';
                    document.getElementById('cacheSize').textContent = cacheSizeMB.toFixed(1) + 'MB';

                    // 获取详细缓存信息
                    const cacheResponse = await fetch('/api/admin/cache/info');
                    const cacheResult = await cacheResponse.json();

                    if (cacheResult.success) {
                        const userCacheSize = (cacheResult.cache_details.user.total_size / (1024 * 1024)).toFixed(1);
                        const hairstyleCacheSize = (cacheResult.cache_details.hairstyle.total_size / (1024 * 1024)).toFixed(1);

                        document.getElementById('userCacheSize').textContent = userCacheSize + ' MB';
                        document.getElementById('hairstyleCacheSize').textContent = hairstyleCacheSize + ' MB';
                    }
                }
            } catch (error) {
                console.error('加载系统信息失败:', error);
            }
        }

        // 清理缓存
        async function cleanCache() {
            const maxAgeHours = parseInt(document.getElementById('maxAgeHours').value);
            const maxSizeMB = parseInt(document.getElementById('maxSizeMB').value);
            const cleanBtn = document.getElementById('cleanCacheBtn');
            const maxAllowed = parseInt(document.getElementById('maxSizeMB').max);

            if (maxAgeHours < 1 || maxAgeHours > 168) {
                showAlert('systemAlert', 'danger', '⚠️ 清理时间范围必须在1-168小时之间');
                return;
            }

            if (maxSizeMB < 10) {
                showAlert('systemAlert', 'danger', '⚠️ 缓存大小限制不能少于10MB');
                return;
            }

            if (maxAllowed && maxSizeMB > maxAllowed) {
                showAlert('systemAlert', 'danger', `⚠️ 缓存大小限制不能超过推荐值 ${maxAllowed}MB (磁盘90%)`);
                return;
            }

            if (!confirm(`确定要清理缓存吗？\n\n清理策略：\n- 删除超过 ${maxAgeHours} 小时的缓存文件\n- 总缓存大小超过 ${maxSizeMB}MB 时删除最旧的文件\n\n此操作不可撤销！`)) {
                return;
            }

            try {
                cleanBtn.disabled = true;
                cleanBtn.textContent = '🧹 清理中...';

                const response = await fetch('/api/admin/cache/clean', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        max_age_hours: maxAgeHours,
                        max_total_size_mb: maxSizeMB
                    })
                });

                const result = await response.json();

                if (result.success) {
                    showAlert('systemAlert', 'success',
                        `✅ 缓存清理完成！<br>删除了 ${result.cleaned_files} 个文件，释放了 ${result.cleaned_size_mb.toFixed(1)}MB 空间`);

                    // 刷新系统信息
                    setTimeout(() => {
                        loadSystemInfo();
                        loadStats();
                    }, 1000);
                } else {
                    showAlert('systemAlert', 'danger', `❌ 清理失败: ${result.error}`);
                }
            } catch (error) {
                showAlert('systemAlert', 'danger', `❌ 网络错误: ${error.message}`);
            } finally {
                cleanBtn.disabled = false;
                cleanBtn.textContent = '🧹 立即清理缓存';
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

        // 缓存文件管理相关函数
        let currentCacheFiles = { user: [], hairstyle: [] };

        // 加载缓存文件列表
        async function loadCacheFiles() {
            try {
                const response = await fetch('/api/admin/cache/files');
                const result = await response.json();

                if (result.success) {
                    currentCacheFiles = result.cache_files;

                    // 更新统计信息
                    document.getElementById('userCacheFileCount').textContent = result.summary.user_files;
                    document.getElementById('userCacheFileSize').textContent = result.summary.user_size_mb.toFixed(1) + ' MB';
                    document.getElementById('hairstyleCacheFileCount').textContent = result.summary.hairstyle_files;
                    document.getElementById('hairstyleCacheFileSize').textContent = result.summary.hairstyle_size_mb.toFixed(1) + ' MB';

                    // 更新文件表格
                    updateCacheFilesTable('user');
                    updateCacheFilesTable('hairstyle');

                    // 默认显示用户图片缓存
                    showCacheFileType('user');
                }
            } catch (error) {
                console.error('加载缓存文件失败:', error);
            }
        }

        // 切换显示的缓存文件类型
        function showCacheFileType(type) {
            // 隐藏所有section
            document.getElementById('userCacheFilesSection').style.display = 'none';
            document.getElementById('hairstyleCacheFilesSection').style.display = 'none';

            // 显示选中的section
            document.getElementById(type + 'CacheFilesSection').style.display = 'block';

            // 更新按钮状态
            document.getElementById('showUserFiles').style.background = type === 'user' ? '#667eea' : '#6c757d';
            document.getElementById('showHairstyleFiles').style.background = type === 'hairstyle' ? '#667eea' : '#6c757d';
        }

        // 更新缓存文件表格
        function updateCacheFilesTable(type) {
            const tbody = document.getElementById(type + 'CacheFilesTable');
            const files = currentCacheFiles[type] || [];

            if (files.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align: center;">暂无缓存文件</td></tr>';
                return;
            }

            tbody.innerHTML = files.map(file => {
                const imageUrl = `/api/admin/cache/image/${type}/${encodeURIComponent(file.filename)}`;
                return `
                <tr>
                    <td style="text-align: center; width: 80px;">
                        <img src="${imageUrl}"
                             style="width: 60px; height: 60px; object-fit: cover; border-radius: 5px; cursor: pointer; border: 1px solid #ddd;"
                             onclick="viewImageModal('${type}', '${file.filename}', '${file.original_filename}', ${file.size}, '${file.modified_time_str}')"
                             title="点击查看大图"
                             onerror="this.style.display='none'; this.parentNode.innerHTML='<span style=\\'color: #999;\\'>❌</span>';">
                    </td>
                    <td><code style="font-size: 12px;">${file.filename}</code></td>
                    <td>${file.original_filename}</td>
                    <td>${(file.size / 1024).toFixed(1)} KB</td>
                    <td>${file.modified_time_str}</td>
                    <td>
                        <button class="btn btn-sm"
                                onclick="viewImageModal('${type}', '${file.filename}', '${file.original_filename}', ${file.size}, '${file.modified_time_str}')"
                                title="查看大图" style="margin-right: 5px;">👁️ 查看</button>
                        <button class="btn btn-sm btn-danger"
                                onclick="deleteCacheFile('${type}', '${file.filename}')"
                                title="删除缓存文件">🗑️ 删除</button>
                    </td>
                </tr>
            `;
            }).join('');
        }

        // 删除单个缓存文件
        async function deleteCacheFile(imageType, filename) {
            if (!confirm(`确定要删除缓存文件 "${filename}" 吗？\n\n此操作不可撤销！`)) {
                return;
            }

            try {
                const response = await fetch(`/api/admin/cache/files/${imageType}/${encodeURIComponent(filename)}`, {
                    method: 'DELETE'
                });

                const result = await response.json();

                if (result.success) {
                    showAlert('cacheFilesAlert', 'success', `✅ ${result.message}`);

                    // 刷新缓存文件列表和系统信息
                    setTimeout(() => {
                        loadCacheFiles();
                        loadSystemInfo();
                        loadStats();
                    }, 1000);
                } else {
                    showAlert('cacheFilesAlert', 'danger', `❌ 删除失败: ${result.error}`);
                }
            } catch (error) {
                showAlert('cacheFilesAlert', 'danger', `❌ 网络错误: ${error.message}`);
            }
        }

        // 在模态对话框中查看图片
        function viewImageModal(imageType, filename, originalFilename, fileSize, modifiedTime) {
            const imageUrl = `/api/admin/cache/image/${imageType}/${encodeURIComponent(filename)}`;

            // 设置模态对话框内容
            document.getElementById('modalImage').src = imageUrl;
            document.getElementById('modalFileName').textContent = filename;
            document.getElementById('modalOriginalFileName').textContent = originalFilename;
            document.getElementById('modalFileSize').textContent = (fileSize / 1024).toFixed(1) + ' KB';
            document.getElementById('modalModifiedTime').textContent = modifiedTime;
            document.getElementById('modalImageType').textContent = imageType === 'user' ? '用户图片缓存' : '发型图片缓存';

            // 显示模态对话框
            document.getElementById('imageModal').style.display = 'block';

            // 添加ESC键关闭功能
            document.addEventListener('keydown', handleModalKeydown);

            // 阻止页面滚动
            document.body.style.overflow = 'hidden';
        }

        // 关闭图片模态对话框
        function closeImageModal() {
            document.getElementById('imageModal').style.display = 'none';
            document.removeEventListener('keydown', handleModalKeydown);
            document.body.style.overflow = 'auto';
        }

        // 处理模态对话框键盘事件
        function handleModalKeydown(event) {
            if (event.key === 'Escape') {
                closeImageModal();
            }
        }

        // 点击模态对话框背景关闭
        document.addEventListener('DOMContentLoaded', function() {
            const modal = document.getElementById('imageModal');
            if (modal) {
                modal.addEventListener('click', function(event) {
                    if (event.target === modal) {
                        closeImageModal();
                    }
                });
            }
        });
    </script>
</body>
</html>
'''

# 启动清理线程
cleanup_thread = threading.Thread(target=cleanup_expired_sessions, daemon=True)
cleanup_thread.start()

# 启动Gemini缓存清理线程
gemini_cleanup_thread = threading.Thread(target=cleanup_gemini_cache, daemon=True)
gemini_cleanup_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)