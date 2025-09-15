from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import tempfile
import os
import uuid
from hairstyle_processor_v2 import HairstyleProcessor
import threading
import time

app = Flask(__name__)
CORS(app)

# 全局存储临时会话数据（生产环境建议用Redis）
sessions = {}
processor = HairstyleProcessor()

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

            # 创建图片访问URL
            base_url = request.url_root.rstrip('/')
            image_url = f"{base_url}/api/image/{session_id}/{image_type}"

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
        with session_lock:
            sessions[session_id]['status'] = 'processing'

        user_image_path = session_data['user_image']
        hairstyle_image_path = session_data['hairstyle_image']

        # 上传到RunningHub
        user_filename = processor.upload_image(user_image_path)
        if not user_filename:
            raise Exception("用户图片上传失败")

        hairstyle_filename = processor.upload_image(hairstyle_image_path)
        if not hairstyle_filename:
            raise Exception("发型图片上传失败")

        # 运行任务
        task_id = processor.run_hairstyle_task(hairstyle_filename, user_filename)
        if not task_id:
            raise Exception("任务启动失败")

        # 等待完成（最多5分钟）
        max_wait = 300
        wait_time = 0

        while wait_time < max_wait:
            status = processor.check_task_status(task_id)
            if status == "SUCCESS":
                break
            elif status in ["FAILED", "CANCELLED"]:
                raise Exception(f"任务失败: {status}")

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
        try:
            if session_data['user_image'] and os.path.exists(session_data['user_image']):
                os.remove(session_data['user_image'])
            if session_data['hairstyle_image'] and os.path.exists(session_data['hairstyle_image']):
                os.remove(session_data['hairstyle_image'])
        except:
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

# 启动清理线程
cleanup_thread = threading.Thread(target=cleanup_expired_sessions, daemon=True)
cleanup_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)