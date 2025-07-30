import tensorflow as tf
import numpy as np
from PIL import Image
import requests
import io
import os

# ไลบรารีสำหรับ LINE Bot และ Flask
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage

# สร้าง Flask application instance
app = Flask(__name__)

# ----------------------------------------------------------------------
# 1. ตั้งค่า LINE API Credentials ของคุณ
# ----------------------------------------------------------------------
# ดึงค่า Channel Access Token และ Channel Secret จาก Environment Variables
# นี่เป็นวิธีที่ปลอดภัยกว่าการใส่ค่าลงในโค้ดโดยตรง
# เมื่อรันบน Render.com หรือบนเครื่องของคุณ (โดยการตั้งค่า os.environ หรือ set/export)
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', None)

# ตรวจสอบว่าได้ตั้งค่า Token/Secret แล้วหรือไม่
if LINE_CHANNEL_ACCESS_TOKEN is None or LINE_CHANNEL_SECRET is None:
    print("------------------------------------------------------------------------------------")
    print("CRITICAL ERROR: LINE_CHANNEL_ACCESS_TOKEN or LINE_CHANNEL_SECRET is not set.")
    print("โปรดตั้งค่า Environment Variables เหล่านี้ก่อนรันแอปพลิเคชัน")
    print("The chatbot will NOT work without these credentials.")
    print("------------------------------------------------------------------------------------")
    # ในการใช้งานจริง ควรจะ raise Exception หรือมีกลไกจัดการ Error ที่ดีกว่านี้
    # แต่สำหรับตัวอย่างนี้ เราจะปล่อยให้รันต่อเพื่อให้เห็นโครงสร้าง
    # raise ValueError("LINE API credentials are not set.")

# สร้าง LineBotApi และ WebhookHandler instances
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ----------------------------------------------------------------------
# 2. โหลดโมเดล AI ของคุณ (.tflite file)
# ----------------------------------------------------------------------
# เปลี่ยน Path ให้ชี้ไปที่ไฟล์ .tflite
MODEL_PATH = 'khunmoa_skin_diagnosis_final_model.tflite'

try:
    # โหลด TFLite model โดยใช้ tf.lite.Interpreter
    interpreter = tf.lite.Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors() # ต้องเรียก allocate_tensors() เสมอ

    # ดึงรายละเอียด Input และ Output ของโมเดล TFLite
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    print("TFLite Model loaded successfully!")
except Exception as e:
    print(f"Error loading TFLite model from {MODEL_PATH}: {e}")
    interpreter = None # ตั้งค่าเป็น None ถ้าโหลดไม่ได้

# ----------------------------------------------------------------------
# 3. กำหนดชื่อ Class (ต้องเรียงลำดับให้ตรงกับตอนที่คุณฝึกโมเดล!)
# ----------------------------------------------------------------------
# นี่คือรายการชื่อคลาสทั้ง 19 ชนิด ที่โมเดลของคุณถูกฝึกมาให้จำแนก
class_names = [
    'Abrasions', 'Acne', 'Actinic Keratosis', 'Basal Cell Carcinoma', 'Bruises',
    'Burns', 'Cut', 'Dermatofibroma', 'Diabetic Wounds', 'Laceration',
    'Melanocytic Nevi', 'Melanoma', 'Normal', 'Pressure Wounds',
    'Seborrheic Keratoses', 'Squamous Cell Carcinoma', 'Surgical Wounds',
    'Vascular Lesion', 'Venous Wounds'
]

# ----------------------------------------------------------------------
# 4. ฟังก์ชันสำหรับการรับ Webhook จาก LINE
# ----------------------------------------------------------------------
# นี่คือ Endpoint ที่ LINE จะส่งข้อมูล (ข้อความ, รูปภาพ) มาให้ Chatbot ของคุณ
@app.route("/callback", methods=['GET', 'POST']) # รับทั้ง GET และ POST
def callback():
    # ดึงค่า X-Line-Signature จาก Header เพื่อยืนยันว่าเป็น Request จาก LINE จริงๆ
    signature = request.headers.get('X-Line-Signature') # ใช้ .get() เพื่อป้องกัน Error ถ้าไม่มี Signature ใน GET Request
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body) # บันทึก Body ลงใน Log (มีประโยชน์ในการ Debug)

    # ถ้าเป็น GET Request (สำหรับการ Verify Webhook หรือ Health Check)
    if request.method == 'GET':
        print("Received GET request to /callback (for verification).")
        return 'OK', 200 # ตอบกลับ 200 OK ทันที

    # ถ้าเป็น POST Request (สำหรับ LINE Event จริงๆ)
    try:
        # ประมวลผล Webhook Event โดยใช้ Line Webhook Handler
        handler.handle(body, signature)
    except InvalidSignatureError:
        # หาก Signature ไม่ถูกต้อง แสดงว่า Request ไม่ได้มาจาก LINE หรือ Channel Secret ผิด
        print("Invalid signature. Please check your channel access token/channel secret or Webhook URL.")
        abort(400) # ส่ง HTTP 400 Bad Request กลับไป
    return 'OK' # ตอบกลับ LINE ว่าได้รับ Request แล้ว

# ----------------------------------------------------------------------
# 5. ฟังก์ชันจัดการข้อความ Text Message
# ----------------------------------------------------------------------
# เมื่อผู้ใช้ส่งข้อความ (Text Message) เข้ามา
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    text_message = event.message.text.lower() # แปลงข้อความเป็นตัวพิมพ์เล็กเพื่อการเปรียบเทียบ
    reply_text = "" # ข้อความตอบกลับเริ่มต้น

    # ตรวจสอบคำทักทาย
    if "สวัสดี" in text_message or "hi" in text_message:
        reply_text = "สวัสดีครับ คุณหมอ AI ยินดีให้บริการครับ! 👋\nส่งรูปภาพผิวหนังหรือบาดแผลมาให้ผมช่วยวิเคราะห์เบื้องต้นได้เลยนะครับ"
    # ตรวจสอบคำถามเกี่ยวกับความสามารถของ Bot
    elif "คืออะไร" in text_message or "ทำอะไรได้" in text_message:
        reply_text = "ผมคือ AI สำหรับวิเคราะห์รูปภาพโรคผิวหนังและบาดแผลเบื้องต้นครับ\nเพียงแค่ส่งรูปภาพเข้ามา ผมจะช่วยระบุประเภทที่ใกล้เคียงที่สุดจาก 19 ชนิดให้ครับ"
    # ตรวจสอบคำขอบคุณ
    elif "ขอบคุณ" in text_message:
        reply_text = "ยินดีครับ หากมีคำถามหรือต้องการให้ช่วยวิเคราะห์อีก ส่งรูปมาได้เลยนะครับ!"
    # ข้อความตอบกลับสำหรับคำถามที่ไม่เข้าใจ
    else:
        reply_text = "ผมยังไม่เข้าใจคำถามครับ ตอนนี้ผมเน้นการวิเคราะห์รูปภาพโรคผิวหนัง/บาดแผลเป็นหลัก\nโปรดส่งรูปภาพเพื่อให้ผมช่วยวิเคราะห์เบื้องต้นครับ 😊"

    # ตอบกลับผู้ใช้ด้วยข้อความ
    line_bot_api.reply_message(
        event.reply_token,
        TextMessage(text=reply_text)
    )

# ----------------------------------------------------------------------
# 6. ฟังก์ชันจัดการรูปภาพ (Image Message)
# ----------------------------------------------------------------------
# เมื่อผู้ใช้ส่งรูปภาพ (Image Message) เข้ามา
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    if interpreter is None: # ตรวจสอบ interpreter แทน model
        line_bot_api.reply_message(
            event.reply_token,
            TextMessage(text="ขออภัยครับ โมเดล AI ยังไม่พร้อมให้บริการ โปรดแจ้งผู้ดูแลระบบ")
        )
        return

    # ดึง Content ของรูปภาพจาก LINE API
    message_content = line_bot_api.get_message_content(event.message.id)
    # แปลง Content ของรูปภาพเป็น BytesIO object เพื่อให้ PIL (Pillow) เปิดได้
    image_bytes = io.BytesIO(message_content.content)

    try:
        # ----------------------------------------------------------------
        # Preprocess image (ขั้นตอนเตรียมรูปภาพก่อนส่งให้โมเดล)
        # ----------------------------------------------------------------
        # 1. เปิดรูปภาพและแปลงเป็น RGB (บางรูปอาจเป็น RGBA หรือ Grayscale)
        img = Image.open(image_bytes).convert('RGB')
        # 2. ปรับขนาดรูปภาพให้เป็น 224x224 พิกเซล (ตามที่โมเดล MobileNetV2 คาดหวัง)
        img = img.resize((224, 224))
        # 3. แปลงรูปภาพเป็น NumPy array
        img_array = np.array(img)
        # 4. Normalize ค่าสีของพิกเซลจาก 0-255 ให้เป็น 0-1 (เหมือนตอนเทรนโมเดล)
        img_array = img_array / 255.0
        # 5. เพิ่ม Dimension สำหรับ Batch Size (โมเดลคาดหวัง Input เป็น (BatchSize, Height, Width, Channels))
        #    จาก (224, 224, 3) เป็น (1, 224, 224, 3)
        img_array = np.expand_dims(img_array, axis=0)

        # ----------------------------------------------------------------
        # Predict ด้วย TFLite Interpreter
        # ----------------------------------------------------------------
        # กำหนด Input Tensor
        interpreter.set_tensor(input_details[0]['index'], img_array.astype(input_details[0]['dtype']))
        
        # รัน Inference
        interpreter.invoke()
        
        # ดึง Output Tensor
        predictions = interpreter.get_tensor(output_details[0]['index'])
        
        predicted_class_index = np.argmax(predictions[0])
        confidence = np.max(predictions[0])
        predicted_class_name = class_names[predicted_class_index]

        # ----------------------------------------------------------------
        # สร้างข้อความตอบกลับ
        # ----------------------------------------------------------------
        reply_text = (
            f"จากการวิเคราะห์เบื้องต้น AI คาดการณ์ว่ารูปภาพนี้มีลักษณะคล้ายกับ:\n"
            f"**{predicted_class_name}**\n"
            f"(ความมั่นใจ: {confidence:.2f})\n\n"
            f"**⚠️ คำเตือนสำคัญ:**\n"
            f"ข้อมูลนี้เป็นเพียงการวิเคราะห์เบื้องต้นจากระบบ AI และไม่สามารถใช้แทนการวินิจฉัยของแพทย์ได้\n"
            f"เพื่อการวินิจฉัยที่ถูกต้องและแม่นยำที่สุด **โปรดปรึกษาแพทย์ผู้เชี่ยวชาญ** หรือผู้เชี่ยวชาญด้านสุขภาพ"
        )

    except Exception as e:
        # หากเกิดข้อผิดพลาดในการประมวลผลรูปภาพ
        reply_text = f"ขออภัยครับ เกิดข้อผิดพลาดในการประมวลผลรูปภาพ: {e}\nโปรดลองอีกครั้งหรือส่งรูปภาพที่ชัดเจนขึ้น"
        print(f"Error processing image: {e}") # พิมพ์ Error ใน Log สำหรับ Debugging

    # ตอบกลับผู้ใช้ด้วยข้อความผลการวิเคราะห์
    line_bot_api.reply_message(
        event.reply_token,
        TextMessage(text=reply_text)
    )

# ----------------------------------------------------------------------
# 7. ส่วนสำหรับรัน Flask App
# ----------------------------------------------------------------------
# บล็อกโค้ดนี้จะรันเมื่อไฟล์ app.py ถูกรันโดยตรง (เช่น python app.py)

