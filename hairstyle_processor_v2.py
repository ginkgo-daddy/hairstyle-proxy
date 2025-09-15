import http.client
import json
import os
import mimetypes
from codecs import encode
import time
import requests
from datetime import datetime
from docx import Document
from docx.shared import Inches
from PIL import Image, ExifTags
import io
import random
import concurrent.futures
import threading
from queue import Queue

class HairstyleProcessor:
    def __init__(self, api_key="b8ef5bbe2d9b46efa3311ce92cc68716", webapp_id=1967522806713946113, max_workers=3):
        self.api_key = api_key
        self.webapp_id = webapp_id
        self.host = "www.runninghub.cn"
        self.results = []
        self.results_lock = threading.Lock()
        self.max_workers = max_workers
           
    def upload_image(self, image_path):
        """Upload image to RunningHub server and return fileName"""
        corrected_path = image_path
        
        conn = http.client.HTTPSConnection(self.host)
        dataList = []
        boundary = 'wL36Yn8afVp8Ag7AmP8qZ0SA4n1v9T'
        
        dataList.append(encode('--' + boundary))
        dataList.append(encode('Content-Disposition: form-data; name=apiKey;'))
        dataList.append(encode('Content-Type: {}'.format('text/plain')))
        dataList.append(encode(''))
        dataList.append(encode(self.api_key))
        
        dataList.append(encode('--' + boundary))
        filename = os.path.basename(corrected_path)
        dataList.append(encode('Content-Disposition: form-data; name=file; filename={0}'.format(filename)))
        
        fileType = mimetypes.guess_type(corrected_path)[0] or 'application/octet-stream'
        dataList.append(encode('Content-Type: {}'.format(fileType)))
        dataList.append(encode(''))
        
        with open(corrected_path, 'rb') as f:
            dataList.append(f.read())
            
        dataList.append(encode('--' + boundary))
        dataList.append(encode('Content-Disposition: form-data; name=fileType;'))
        dataList.append(encode('Content-Type: {}'.format('text/plain')))
        dataList.append(encode(''))
        dataList.append(encode("image"))
        dataList.append(encode('--'+boundary+'--'))
        dataList.append(encode(''))
        
        body = b'\r\n'.join(dataList)
        headers = {
            'Host': self.host,
            'Content-type': 'multipart/form-data; boundary={}'.format(boundary)
        }
        
        try:
            conn.request("POST", "/task/openapi/upload", body, headers)
            res = conn.getresponse()
            data = res.read()
            result = json.loads(data.decode("utf-8"))
            
            if result.get("code") == 0:
                print(f"Upload successful for {image_path}: {result['data']['fileName']}")
                return result["data"]["fileName"]
            else:
                print(f"Upload failed for {image_path}: {result}")
                print(f"API Response: {result}")
                return None
        except Exception as e:
            print(f"Error uploading {image_path}: {e}")
            return None
        finally:
            conn.close()
            # Clean up temporary corrected file if it was created
            if corrected_path != image_path and os.path.exists(corrected_path):
                try:
                    os.remove(corrected_path)
                except:
                    pass
    
    def run_hairstyle_task(self, hairstyle_filename, user_filename, max_retries=10, retry_delay=20):
        """Run AI hairstyle transfer task with retry mechanism for TASK_QUEUE_MAXED"""
        payload = json.dumps({
            "webappId": self.webapp_id,
            "apiKey": self.api_key,
            "nodeInfoList": [
                {
                    "nodeId": "238",
                    "fieldName": "image",
                    "fieldValue": hairstyle_filename,
                    "description": "hair"
                },
                {
                    "nodeId": "239",
                    "fieldName": "image",
                    "fieldValue": user_filename,
                    "description": "usr"
                }
            ]
        })

        headers = {
            'Host': self.host,
            'Content-Type': 'application/json'
        }

        for attempt in range(max_retries):
            conn = http.client.HTTPSConnection(self.host)
            try:
                conn.request("POST", "/task/openapi/ai-app/run", payload, headers)
                res = conn.getresponse()
                data = res.read()
                result = json.loads(data.decode("utf-8"))

                if result.get("code") == 0:
                    print(f"Task started successfully: {result['data']['taskId']}")
                    return result["data"]["taskId"]
                elif result.get("message") == "TASK_QUEUE_MAXED":
                    print(f"Task queue is full (attempt {attempt + 1}/{max_retries}), waiting {retry_delay} seconds before retry...")
                    if attempt < max_retries - 1:  # Don't sleep on the last attempt
                        time.sleep(retry_delay)
                        continue
                    else:
                        print(f"Max retries reached, task queue still full")
                        return None
                else:
                    print(f"Task failed: {result}")
                    print(f"API Response: {result}")
                    return None
            except Exception as e:
                print(f"Error running task (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    return None
            finally:
                conn.close()

        return None
    
    def check_task_status(self, task_id):
        """Check task status"""
        conn = http.client.HTTPSConnection(self.host)
        payload = json.dumps({
            "apiKey": self.api_key,
            "taskId": task_id
        })
        
        headers = {
            'Host': self.host,
            'Content-Type': 'application/json'
        }
        
        try:
            conn.request("POST", "/task/openapi/status", payload, headers)
            res = conn.getresponse()
            data = res.read()
            result = json.loads(data.decode("utf-8"))
            
            if result.get("code") == 0:
                return result["data"]
            else:
                print(f"Status check failed: {result}")
                return None
        except Exception as e:
            print(f"Error checking status: {e}")
            return None
        finally:
            conn.close()
    
    def get_task_results(self, task_id):
        """Get task results"""
        conn = http.client.HTTPSConnection(self.host)
        payload = json.dumps({
            "apiKey": self.api_key,
            "taskId": task_id
        })
        
        headers = {
            'Host': self.host,
            'Content-Type': 'application/json'
        }
        
        try:
            conn.request("POST", "/task/openapi/outputs", payload, headers)
            res = conn.getresponse()
            data = res.read()
            result = json.loads(data.decode("utf-8"))
            
            if result.get("code") == 0:
                return result["data"]
            else:
                print(f"Get results failed: {result}")
                return None
        except Exception as e:
            print(f"Error getting results: {e}")
            return None
        finally:
            conn.close()
    
    def download_image(self, url, save_path):
        """Download image from URL"""
        try:
            response = requests.get(url)
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                return True
            else:
                print(f"Failed to download {url}")
                return False
        except Exception as e:
            print(f"Error downloading {url}: {e}")
            return False
    
    def create_combined_image(self, hairstyle_path, user_path, result_paths, output_path):
        """Create a combined image with hairstyle reference, user photo, and all generated results"""
        try:
            # Open hairstyle and user images
            hairstyle_img = Image.open(hairstyle_path)
            user_img = Image.open(user_path)
            
            # Open all result images
            result_imgs = []
            for result_path in result_paths:
                if os.path.exists(result_path):
                    result_imgs.append(Image.open(result_path))
            
            if not result_imgs:
                print("No result images found")
                return False
            
            # Collect all images
            all_imgs = [hairstyle_img, user_img] + result_imgs
            
            # Convert to RGB if necessary
            for i, img in enumerate(all_imgs):
                if img.mode != 'RGB':
                    all_imgs[i] = img.convert('RGB')
            
            # Define target height (use the minimum height among all images, but at least 512px)
            target_height = max(512, min(img.height for img in all_imgs))
            
            # Resize all images to the same height while maintaining aspect ratio
            def resize_to_height(img, target_height):
                aspect_ratio = img.width / img.height
                target_width = int(target_height * aspect_ratio)
                return img.resize((target_width, target_height), Image.Resampling.LANCZOS)
            
            resized_imgs = [resize_to_height(img, target_height) for img in all_imgs]
            
            # Calculate total width
            total_width = sum(img.width for img in resized_imgs)
            
            # Create new image for the combined result
            combined_img = Image.new('RGB', (total_width, target_height), (255, 255, 255))
            
            # Paste images side by side
            x_offset = 0
            for img in resized_imgs:
                combined_img.paste(img, (x_offset, 0))
                x_offset += img.width
            
            # Save the combined image
            combined_img.save(output_path, 'PNG', quality=95)
            print(f"Combined image saved: {output_path}")
            return True
            
        except Exception as e:
            print(f"Error creating combined image: {e}")
            return False
    
    def resize_image_for_word(self, image_path, max_width=2.5):
        """Resize image to fit in Word document"""
        try:
            with Image.open(image_path) as img:
                width, height = img.size
                aspect_ratio = height / width
                
                if width > max_width * 96:  # 96 DPI default
                    new_width = max_width
                    new_height = new_width * aspect_ratio
                    return new_width, new_height
                else:
                    return width / 96, height / 96
        except:
            return max_width, max_width
    
    def process_single_combination(self, task_info):
        """Process a single user-hairstyle combination"""
        user_full_path, hairstyle_full_path, user_file, hairstyle_file, gender_name, results_dir = task_info
        
        print(f"[{threading.current_thread().name}] Processing: {user_file} + {hairstyle_file}")
        
        try:
            # Upload images
            print(f"[{threading.current_thread().name}] Uploading user image...")
            user_filename = self.upload_image(user_full_path)
            if not user_filename:
                return
            
            print(f"[{threading.current_thread().name}] Uploading hairstyle image...")
            hairstyle_filename = self.upload_image(hairstyle_full_path)
            if not hairstyle_filename:
                return
            
            # Run task
            print(f"[{threading.current_thread().name}] Running hairstyle transfer task...")
            task_id = self.run_hairstyle_task(hairstyle_filename, user_filename)
            if not task_id:
                return
            
            # Wait for completion
            print(f"[{threading.current_thread().name}] Task {task_id} started, waiting for completion...")
            max_wait = 1000  # 5 minutes max
            wait_time = 0
            
            while wait_time < max_wait:
                status = self.check_task_status(task_id)
                if status == "SUCCESS":
                    break
                elif status in ["FAILED", "CANCELLED"]:
                    print(f"[{threading.current_thread().name}] Task failed with status: {status}")
                    return
                
                time.sleep(10)
                wait_time += 10
                if wait_time % 30 == 0:  # Print every 30 seconds
                    print(f"[{threading.current_thread().name}] Still processing... ({wait_time}s)")
            
            if status != "SUCCESS":
                print(f"[{threading.current_thread().name}] Task did not complete successfully: {status}")
                return
            
            # Get results
            print(f"[{threading.current_thread().name}] Getting results...")
            results = self.get_task_results(task_id)
            if not results:
                return
            
            # Download result images and create combined images
            result_paths = []
            result_filenames = []
            
            # Download all result images first
            for i, result in enumerate(results):
                result_url = result.get("fileUrl")
                if result_url:
                    result_filename = f"{gender_name}_{user_file}_{hairstyle_file}_result_{i}.png"
                    result_path = os.path.join(results_dir, result_filename)
                    
                    if self.download_image(result_url, result_path):
                        result_paths.append(result_path)
                        result_filenames.append(result_filename)
            
            # Create one combined image with all results (hairstyle + user + 4 results)
            if result_paths:
                combined_filename = f"{gender_name}_{user_file}_{hairstyle_file}_combined_all.png"
                combined_path = os.path.join(results_dir, combined_filename)
                
                if self.create_combined_image(hairstyle_full_path, user_full_path, result_paths, combined_path):
                    print(f"[{threading.current_thread().name}] Created combined image: {combined_filename}")
                
                # Store result info (thread-safe)
                with self.results_lock:
                    self.results.append({
                        'gender': gender_name,
                        'user_image': user_full_path,
                        'hairstyle_image': hairstyle_full_path,
                        'result_images': result_paths,
                        'combined_image': combined_path if os.path.exists(combined_path) else None,
                        'user_filename': user_file,
                        'hairstyle_filename': hairstyle_file,
                        'result_filenames': result_filenames,
                        'combined_filename': combined_filename
                    })
            
            print(f"[{threading.current_thread().name}] Completed: {user_file} + {hairstyle_file}")
            
        except Exception as e:
            print(f"[{threading.current_thread().name}] Error processing {user_file} + {hairstyle_file}: {e}")
    
    def process_gender_folder(self, gender_path, gender_name):
        """Process all combinations for a gender (man/woman) with concurrent processing"""
        hairstyle_path = os.path.join(gender_path, "hairstyle")
        user_path = os.path.join(gender_path, "user")
        
        if not os.path.exists(hairstyle_path) or not os.path.exists(user_path):
            print(f"Missing hairstyle or user folder for {gender_name}")
            return
        
        hairstyle_files = [f for f in os.listdir(hairstyle_path) if f.lower().endswith(('.jpg', '.jpeg', '.png','.JPG', '.JPEG', '.PNG'))]
        user_files = [f for f in os.listdir(user_path) if f.lower().endswith(('.jpg', '.jpeg', '.png','.JPG', '.JPEG', '.PNG'))]
        
        # For women, randomly select 50 hairstyles
        if gender_name == "woman" and len(hairstyle_files) > 50:
            hairstyle_files = random.sample(hairstyle_files, 50)
            print(f"Randomly selected 50 hairstyles for women from {len(os.listdir(hairstyle_path))} total")
        
        print(f"Processing {gender_name}: {len(hairstyle_files)} hairstyles × {len(user_files)} users = {len(hairstyle_files) * len(user_files)} combinations")
        
        results_dir = f"results_{gender_name}"
        os.makedirs(results_dir, exist_ok=True)
        
        # Create task list
        tasks = []
        for user_file in user_files:
            for hairstyle_file in hairstyle_files:
                user_full_path = os.path.join(user_path, user_file)
                hairstyle_full_path = os.path.join(hairstyle_path, hairstyle_file)
                task_info = (user_full_path, hairstyle_full_path, user_file, hairstyle_file, gender_name, results_dir)
                tasks.append(task_info)
                # break
        
        # Process tasks concurrently
        print(f"Starting concurrent processing with {self.max_workers} workers...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_task = {executor.submit(self.process_single_combination, task): task for task in tasks}
            
            # Process completed tasks
            completed = 0
            for future in concurrent.futures.as_completed(future_to_task):
                completed += 1
                task = future_to_task[future]
                try:
                    future.result()
                    print(f"Progress: {completed}/{len(tasks)} combinations completed")
                except Exception as exc:
                    user_file, hairstyle_file = task[2], task[3]
                    print(f'Task {user_file} + {hairstyle_file} generated an exception: {exc}')
        
        print(f"Completed processing {gender_name} folder")
    
    def create_word_document(self, output_path="hairstyle_results.docx"):
        """Create Word document with all results"""
        doc = Document()
        doc.add_heading('发型换装结果', 0)
        
        doc.add_paragraph(f'生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        doc.add_paragraph(f'总共处理: {len(self.results)} 个组合')
        
        for i, result in enumerate(self.results):
            doc.add_heading(f'结果 {i+1}: {result["gender"]} - {result["user_filename"]} + {result["hairstyle_filename"]}', level=1)
            
            # Add combined image if available
            if result.get('combined_image') and os.path.exists(result['combined_image']):
                doc.add_paragraph('拼接图片 (发型参考 + 用户照片 + 生成结果):')
                width, height = self.resize_image_for_word(result['combined_image'], max_width=6.0)  # Wider for combined image
                paragraph = doc.add_paragraph()
                run = paragraph.add_run()
                run.add_picture(result['combined_image'], width=Inches(width), height=Inches(height))
                doc.add_paragraph()  # Add some space
            
            # Create table for individual images
            doc.add_paragraph('单独图片:')
            result_images = result.get('result_images', [])
            num_cols = 2 + len(result_images)  # hairstyle + user + result images
            table = doc.add_table(rows=2, cols=num_cols)
            table.style = 'Table Grid'
            
            # Headers
            hdr_cells = table.rows[0].cells
            hdr_cells[0].text = '发型参考图'
            hdr_cells[1].text = '用户照片'
            for j in range(len(result_images)):
                hdr_cells[2 + j].text = f'生成结果{j+1}'
            
            # Images
            img_cells = table.rows[1].cells
            
            # Add hairstyle image
            if os.path.exists(result['hairstyle_image']):
                width, height = self.resize_image_for_word(result['hairstyle_image'])
                paragraph = img_cells[0].paragraphs[0]
                run = paragraph.runs[0] if paragraph.runs else paragraph.add_run()
                run.add_picture(result['hairstyle_image'], width=Inches(width), height=Inches(height))
            
            # Add user image
            if os.path.exists(result['user_image']):
                width, height = self.resize_image_for_word(result['user_image'])
                paragraph = img_cells[1].paragraphs[0]
                run = paragraph.runs[0] if paragraph.runs else paragraph.add_run()
                run.add_picture(result['user_image'], width=Inches(width), height=Inches(height))
            
            # Add result images
            for j, result_image in enumerate(result_images):
                if os.path.exists(result_image):
                    width, height = self.resize_image_for_word(result_image)
                    paragraph = img_cells[2 + j].paragraphs[0]
                    run = paragraph.runs[0] if paragraph.runs else paragraph.add_run()
                    run.add_picture(result_image, width=Inches(width), height=Inches(height))
            
            doc.add_page_break()
        
        doc.save(output_path)
        print(f"Word document saved: {output_path}")

def main():
    hair_base_path = "/Users/alex_wu/work/hair"
    
    # Set random seed for reproducible results
    random.seed(42)
    
    processor = HairstyleProcessor(max_workers=3)
    
    # Process men's hairstyles
    man_path = os.path.join(hair_base_path, "man")
    if os.path.exists(man_path):
        print("Starting men's hairstyle processing...")
        processor.process_gender_folder(man_path, "man")
    
    # Process women's hairstyles (with random selection of 50)
    woman_path = os.path.join(hair_base_path, "woman")
    if os.path.exists(woman_path):
        print("Starting women's hairstyle processing...")
        processor.process_gender_folder(woman_path, "woman")
    
    # Create Word document with all results
    if processor.results:
        processor.create_word_document("hairstyle_results.docx")
        print(f"Processing complete! Generated {len(processor.results)} results.")
    else:
        print("No results generated.")

if __name__ == "__main__":
    main()