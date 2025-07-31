import tensorflow as tf
import numpy as np
from PIL import Image
import requests
import io
import os
import datetime # สำหรับ timestamp

# ไลบรารีสำหรับ LINE Bot
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage

# ไลบรารีสำหรับ Firebase/Firestore
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# ----------------------------------------------------------------------
# 0. การตั้งค่า Firebase/Firestore
# ----------------------------------------------------------------------
# Cloud Functions จะใช้ Service Account เริ่มต้นของ Function เอง
# ซึ่งโดยปกติจะมีสิทธิ์ในการเข้าถึง Firestore อยู่แล้ว
# หากคุณรันบนเครื่อง local และต้องการใช้ Service Account Key:
# cred = credentials.Certificate("path/to/your/serviceAccountKey.json")
# firebase_admin.initialize_app(cred)
# สำหรับ Cloud Functions เพียงพอที่จะเรียก initialize_app โดยไม่มี argument
try:
    firebase_admin.initialize_app()
    db = firestore.client()
    print("Firestore initialized successfully!")
except Exception as e:
    print(f"Error initializing Firestore: {e}")
    db = None # ตั้งค่า db เป็น None ถ้ามีปัญหาในการเชื่อมต่อ

# ----------------------------------------------------------------------
# 1. ตั้งค่า LINE API Credentials ของคุณ
# ----------------------------------------------------------------------
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('+ejYKoOlgc2wwEki1alzwDcWGSXoAkd2f+XEWDORDo4pNjt8yvlNVvd80EEXdzkwEP5FxWj+f6UOiXbDyM9BOhfRyfrU42EFkV+XKk1M8EEQdRU2RyE6QCi+lRqpVmGrJCJ8NbfOCWdFaN1Q3qv51gdB04t89/1O/w1cDnyilFU=', None)
LINE_CHANNEL_SECRET = os.getenv('b53014031bc26ccf4683475d5f13470e', None)

if LINE_CHANNEL_ACCESS_TOKEN is None or LINE_CHANNEL_SECRET is None:
    print("CRITICAL ERROR: LINE_CHANNEL_ACCESS_TOKEN or LINE_CHANNEL_SECRET is not set.")
    pass

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ----------------------------------------------------------------------
# 2. โหลดโมเดล AI ของคุณ (.tflite file)
# ----------------------------------------------------------------------
MODEL_PATH = 'khunmoa_skin_diagnosis_final_model.tflite'

try:
    interpreter = tf.lite.Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    print("TFLite Model loaded successfully!")
except Exception as e:
    print(f"Error loading TFLite model from {MODEL_PATH}: {e}")
    interpreter = None

# ----------------------------------------------------------------------
# 3. กำหนดชื่อ Class และรายละเอียดเพิ่มเติม
# ----------------------------------------------------------------------
# นี่คือรายการชื่อคลาสทั้ง 19 ชนิด ที่โมเดลของคุณถูกฝึกมาให้จำแนก
# ปรับเปลี่ยนให้เป็น Dictionary เพื่อเก็บทั้งชื่อภาษาอังกฤษและภาษาไทย
class_names_map = [
    {'english': 'Abrasions', 'thai': 'แผลถลอก'},
    {'english': 'Acne', 'thai': 'สิว'},
    {'english': 'Actinic Keratosis', 'thai': 'ติ่งเนื้อจากแสงแดด'},
    {'english': 'Basal Cell Carcinoma', 'thai': 'มะเร็งผิวหนังชนิดเบเซลเซลล์'},
    {'english': 'Bruises', 'thai': 'รอยฟกช้ำ'},
    {'english': 'Burns', 'thai': 'แผลไหม้'},
    {'english': 'Cut', 'thai': 'บาดแผลถูกของมีคม'},
    {'english': 'Dermatofibroma', 'thai': 'เนื้องอกผิวหนังชนิดเดอร์มาโตไฟโบรมา'},
    {'english': 'Diabetic Wounds', 'thai': 'แผลเบาหวาน'},
    {'english': 'Laceration', 'thai': 'แผลฉีกขาด'},
    {'english': 'Melanocytic Nevi', 'thai': 'ไฝ'},
    {'english': 'Melanoma', 'thai': 'มะเร็งผิวหนังชนิดเมลาโนมา'},
    {'english': 'Normal', 'thai': 'ผิวปกติ'},
    {'english': 'Pressure Wounds', 'thai': 'แผลกดทับ'},
    {'english': 'Seborrheic Keratoses', 'thai': 'กระเนื้อ'},
    {'english': 'Squamous Cell Carcinoma', 'thai': 'มะเร็งผิวหนังชนิดสความัสเซลล์'},
    {'english': 'Surgical Wounds', 'thai': 'แผลผ่าตัด'},
    {'english': 'Vascular Lesion', 'thai': 'รอยโรคเส้นเลือด'},
    {'english': 'Venous Wounds', 'thai': 'แผลหลอดเลือดดำบกพร่อง'}
]

# สร้าง list ของชื่อภาษาอังกฤษสำหรับใช้กับ np.argmax
class_names = [item['english'] for item in class_names_map]

# Dictionary สำหรับเก็บข้อมูลเพิ่มเติมของแต่ละประเภทอาการ
# คุณสามารถแก้ไขข้อมูลเหล่านี้ให้ถูกต้องและครบถ้วนตามที่คุณต้องการได้เลยนะครับ
class_details = {
    'Abrasions': {
        'treatment': 'ทำความสะอาดแผลด้วยน้ำสะอาดและสบู่เบาๆ ทาครีมฆ่าเชื้อและปิดด้วยผ้าก๊อซ',
        'avoid': 'หลีกเลี่ยงการแกะเกาแผล และไม่ให้แผลโดนสิ่งสกปรก',
        'severe_warning': 'หากมีเลือดออกมาก แผลลึก มีหนอง บวมแดง หรือปวดมาก ควรพบแพทย์ทันที'
    },
    'Acne': {
        'treatment': 'ใช้ผลิตภัณฑ์ทำความสะอาดผิวหน้าสำหรับสิว ทายาแต้มสิวที่มีส่วนผสมของ Benzoyl Peroxide หรือ Salicylic Acid',
        'avoid': 'หลีกเลี่ยงการบีบสิว การใช้เครื่องสำอางที่อุดตันรูขุมขน และอาหารที่มีน้ำตาลสูง',
        'severe_warning': 'หากสิวอักเสบมาก เป็นสิวหัวช้าง หรือมีอาการปวดรุนแรง ควรปรึกษาแพทย์ผิวหนัง'
    },
    'Actinic Keratosis': {
        'treatment': 'ปรึกษาแพทย์ผิวหนังเพื่อการรักษา เช่น การจี้ด้วยความเย็น การใช้ยาเฉพาะที่ หรือการผ่าตัดเล็ก',
        'avoid': 'หลีกเลี่ยงการโดนแสงแดดจัดโดยตรง และควรทาครีมกันแดดเป็นประจำ',
        'severe_warning': 'หากรอยโรคมีการเปลี่ยนแปลงขนาด สี หรือมีเลือดออก ควรพบแพทย์โดยเร็วที่สุด เพราะอาจพัฒนาเป็นมะเร็งผิวหนังได้'
    },
    'Basal Cell Carcinoma': {
        'treatment': 'ปรึกษาแพทย์ผิวหนังเพื่อการรักษา เช่น การผ่าตัด การฉายรังสี หรือการใช้ยาเฉพาะที่',
        'avoid': 'หลีกเลี่ยงการโดนแสงแดดจัด และควรตรวจผิวหนังเป็นประจำ',
        'severe_warning': 'เป็นมะเร็งผิวหนังที่ต้องได้รับการรักษาโดยแพทย์ผู้เชี่ยวชาญทันที'
    },
    'Bruises': {
        'treatment': 'ประคบเย็นในช่วง 24-48 ชั่วโมงแรก จากนั้นประคบอุ่นเพื่อช่วยให้เลือดไหลเวียนดีขึ้น',
        'avoid': 'หลีกเลี่ยงการนวดหรือกดบริเวณที่ช้ำแรงๆ ในช่วงแรก',
        'severe_warning': 'หากรอยช้ำใหญ่ขึ้นอย่างรวดเร็ว ปวดมากผิดปกติ หรือเกิดจากการบาดเจ็บรุนแรง ควรพบแพทย์'
    },
    'Burns': {
        'treatment': 'แผลไหม้ระดับ 1-2: ล้างด้วยน้ำสะอาดหรือน้ำเกลือ ประคบเย็น ทายาสำหรับแผลไหม้',
        'avoid': 'ห้ามใช้ยาสีฟัน น้ำปลา หรือน้ำแข็งประคบแผลไหม้',
        'severe_warning': 'แผลไหม้ระดับ 3 ขึ้นไป แผลใหญ่ มีตุ่มพองขนาดใหญ่ หรือไหม้บริเวณใบหน้า มือ เท้า อวัยวะเพศ ควรพบแพทย์ทันที'
    },
    'Cut': {
        'treatment': 'ทำความสะอาดแผลด้วยน้ำสะอาดและสบู่ ทาครีมฆ่าเชื้อ ปิดด้วยผ้าก๊อซหรือพลาสเตอร์',
        'avoid': 'หลีกเลี่ยงการให้แผลโดนน้ำสกปรก และการแกะเกา',
        'severe_warning': 'หากแผลลึก เลือดออกไม่หยุด มีหนอง หรือปวดมาก ควรพบแพทย์เพื่อเย็บแผลหรือรับการรักษา'
    },
    'Dermatofibroma': {
        'treatment': 'โดยทั่วไปไม่จำเป็นต้องรักษา หากต้องการเอาออกเพื่อความสวยงาม สามารถปรึกษาแพทย์เพื่อผ่าตัดเล็กได้',
        'avoid': 'หลีกเลี่ยงการแกะเกาบ่อยๆ',
        'severe_warning': 'หากมีการเปลี่ยนแปลงขนาด สี หรือมีอาการเจ็บปวด ควรปรึกษาแพทย์เพื่อตรวจวินิจฉัยเพิ่มเติม'
    },
    'Diabetic Wounds': {
        'treatment': 'ทำความสะอาดแผลอย่างสม่ำเสมอ ควบคุมระดับน้ำตาลในเลือด และปรึกษาแพทย์เพื่อการดูแลแผลที่เหมาะสม',
        'avoid': 'หลีกเลี่ยงการเดินเท้าเปล่า และการใส่รองเท้าที่ไม่เหมาะสม',
        'severe_warning': 'แผลเบาหวานมักหายยากและเสี่ยงต่อการติดเชื้อสูง ควรพบแพทย์ผู้เชี่ยวชาญทันที'
    },
    'Laceration': {
        'treatment': 'ทำความสะอาดแผล ห้ามเลือด และปรึกษาแพทย์เพื่อประเมินว่าต้องเย็บแผลหรือไม่',
        'avoid': 'หลีกเลี่ยงการสัมผัสแผลด้วยมือที่ไม่สะอาด',
        'severe_warning': 'หากแผลลึก กว้าง เลือดออกมาก หรือมีสิ่งแปลกปลอมติดอยู่ในแผล ควรพบแพทย์ทันที'
    },
    'Melanocytic Nevi': {
        'treatment': 'โดยทั่วไปไม่จำเป็นต้องรักษา แต่ควรสังเกตการเปลี่ยนแปลง',
        'avoid': 'หลีกเลี่ยงการแกะเกาไฝ และควรทาครีมกันแดด',
        'severe_warning': 'หากไฝมีการเปลี่ยนแปลงขนาด รูปร่าง สี ขอบไม่เรียบ มีอาการคัน หรือมีเลือดออก ควรปรึกษาแพทย์ผิวหนังทันที (อาจเป็นสัญญาณของมะเร็งผิวหนัง)'
    },
    'Melanoma': {
        'treatment': 'ต้องได้รับการรักษาโดยแพทย์ผู้เชี่ยวชาญทันที เช่น การผ่าตัด การฉายรังสี หรือเคมีบำบัด',
        'avoid': 'หลีกเลี่ยงการโดนแสงแดดจัด และควรตรวจผิวหนังเป็นประจำ',
        'severe_warning': 'เป็นมะเร็งผิวหนังชนิดร้ายแรงที่สุด ต้องได้รับการวินิจฉัยและรักษาโดยแพทย์ผู้เชี่ยวชาญโดยเร็วที่สุด'
    },
    'Normal': {
        'treatment': 'ดูแลผิวพรรณให้สะอาด ชุ่มชื้น และทาครีมกันแดดเป็นประจำ',
        'avoid': 'ไม่มีข้อควรหลีกเลี่ยงเฉพาะเจาะจง แต่ควรดูแลสุขภาพโดยรวม',
        'severe_warning': 'หากมีอาการผิดปกติใดๆ เกิดขึ้น ควรปรึกษาแพทย์'
    },
    'Pressure Wounds': {
        'treatment': 'ลดแรงกดทับบริเวณแผล พลิกตัวบ่อยๆ ทำความสะอาดแผล และปรึกษาแพทย์เพื่อการดูแลแผลที่เหมาะสม',
        'avoid': 'หลีกเลี่ยงการนอนหรือนั่งท่าเดิมเป็นเวลานาน',
        'severe_warning': 'หากแผลลึก มีการติดเชื้อ หรือมีไข้ ควรพบแพทย์ทันที'
    },
    'Seborrheic Keratoses': {
        'treatment': 'โดยทั่วไปไม่จำเป็นต้องรักษา หากต้องการเอาออกเพื่อความสวยงาม สามารถปรึกษาแพทย์เพื่อจี้ด้วยความเย็นหรือเลเซอร์ได้',
        'avoid': 'ไม่มีข้อควรหลีกเลี่ยงเฉพาะเจาะจง',
        'severe_warning': 'หากมีการเปลี่ยนแปลงขนาด สี หรือมีอาการคัน/เจ็บปวด ควรปรึกษาแพทย์เพื่อตรวจวินิจฉัยเพิ่มเติม'
    },
    'Squamous Cell Carcinoma': {
        'treatment': 'ปรึกษาแพทย์ผิวหนังเพื่อการรักษา เช่น การผ่าตัด การฉายรังสี หรือการใช้ยาเฉพาะที่',
        'avoid': 'หลีกเลี่ยงการโดนแสงแดดจัด และควรตรวจผิวหนังเป็นประจำ',
        'severe_warning': 'เป็นมะเร็งผิวหนังที่ต้องได้รับการรักษาโดยแพทย์ผู้เชี่ยวชาญทันที'
    },
    'Surgical Wounds': {
        'treatment': 'ทำความสะอาดแผลตามคำแนะนำของแพทย์ เปลี่ยนผ้าปิดแผลตามกำหนด และสังเกตอาการติดเชื้อ',
        'avoid': 'หลีกเลี่ยงการให้แผลโดนน้ำโดยไม่จำเป็น และการยกของหนัก',
        'severe_warning': 'หากแผลบวมแดงร้อน มีหนอง มีไข้ หรือปวดมาก ควรพบแพทย์ทันที'
    },
    'Vascular Lesion': {
        'treatment': 'ปรึกษาแพทย์ผิวหนังเพื่อการวินิจฉัยและวางแผนการรักษา เช่น เลเซอร์ การผ่าตัด หรือการฉีดสารบางชนิด',
        'avoid': 'หลีกเลี่ยงการแกะเกาหรือทำให้เกิดการบาดเจ็บ',
        'severe_warning': 'หากมีการเปลี่ยนแปลงขนาด สี หรือมีเลือดออก ควรปรึกษาแพทย์'
    },
    'Venous Wounds': {
        'treatment': 'ทำความสะอาดแผล พันผ้ายืดหรือใส่ถุงน่องรัด เพื่อช่วยการไหลเวียนของเลือด และปรึกษาแพทย์เพื่อการดูแลแผลที่เหมาะสม',
        'avoid': 'หลีกเลี่ยงการยืนหรือนั่งห้อยขานานๆ',
        'severe_warning': 'หากแผลมีการติดเชื้อ บวมแดงร้อน หรือมีไข้ ควรพบแพทย์ทันที'
    }
}

# Dictionary สำหรับเก็บข้อมูลวิธีรักษาอาการเบื้องต้นทั่วไป
# คุณสามารถเพิ่มอาการและวิธีรักษาได้ตามต้องการ
common_symptoms_treatments = {
    'ปวดหัว': {
        'treatment': 'พักผ่อนให้เพียงพอ ดื่มน้ำมากๆ และอาจรับประทานยาแก้ปวดพื้นฐาน เช่น พาราเซตามอล',
        'warning': 'หากปวดหัวรุนแรงขึ้นเรื่อยๆ มีไข้สูง คอแข็ง หรือมีอาการผิดปกติอื่นๆ ควรรีบพบแพทย์'
    },
    'ปวดท้อง': {
        'treatment': 'ดื่มน้ำอุ่น พักผ่อน และหลีกเลี่ยงอาหารรสจัดหรือย่อยยาก',
        'warning': 'หากปวดท้องรุนแรง ปวดบิด มีไข้ คลื่นไส้อาเจียน หรือถ่ายเป็นเลือด ควรรีบพบแพทย์'
    },
    'เจ็บคอ': {
        'treatment': 'ดื่มน้ำอุ่น กลั้วคอด้วยน้ำเกลือ พักผ่อนให้เพียงพอ และหลีกเลี่ยงอาหารรสจัด',
        'warning': 'หากเจ็บคอมากจนกลืนลำบาก มีไข้สูง หายใจลำบาก หรือมีหนองในลำคอ ควรรีบพบแพทย์'
    },
    'เป็นไข้': {
        'treatment': 'เช็ดตัวลดไข้ ดื่มน้ำมากๆ พักผ่อน และรับประทานยาลดไข้ เช่น พาราเซตามอล',
        'warning': 'หากไข้สูงไม่ลด มีผื่นขึ้น หายใจลำบาก หรือมีอาการชัก ควรรีบพบแพทย์'
    },
    'ไอ': {
        'treatment': 'ดื่มน้ำอุ่นมากๆ จิบน้ำผึ้งผสมมะนาว หรือใช้ยาแก้ไอตามอาการ',
        'warning': 'หากไอเรื้อรัง ไอมีเสมหะปนเลือด หายใจลำบาก หรือมีไข้สูง ควรรีบพบแพทย์'
    },
    'ท้องเสีย': {
        'treatment': 'ดื่มน้ำเกลือแร่ (ORS) เพื่อชดเชยน้ำและเกลือแร่ที่สูญเสียไป และรับประทานอาหารอ่อนๆ',
        'warning': 'หากท้องเสียรุนแรง ถ่ายเป็นน้ำจำนวนมาก มีไข้สูง ปวดท้องมาก หรือมีอาการขาดน้ำ ควรรีบพบแพทย์'
    }
}


# ----------------------------------------------------------------------
# ฟังก์ชันช่วยในการจัดการสถานะและข้อมูลใน Firestore
# ----------------------------------------------------------------------
# Collection สำหรับเก็บสถานะการสนทนาของผู้ใช้
USER_STATES_COLLECTION = 'user_states'
# Collection สำหรับเก็บข้อมูลการวินิจฉัยที่สมบูรณ์
DIAGNOSES_COLLECTION = 'diagnoses'

def get_user_state(user_id):
    """ดึงสถานะปัจจุบันและข้อมูลชั่วคราวของผู้ใช้จาก Firestore."""
    if db is None:
        print("Firestore is not initialized. Cannot get user state.")
        return {'state': 'idle', 'data': {}}
    
    doc_ref = db.collection(USER_STATES_COLLECTION).document(user_id)
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    return {'state': 'idle', 'data': {}} # สถานะเริ่มต้นถ้าไม่มีข้อมูล

def update_user_state(user_id, state, data=None):
    """อัปเดตสถานะและข้อมูลชั่วคราวของผู้ใช้ใน Firestore."""
    if db is None:
        print("Firestore is not initialized. Cannot update user state.")
        return
    
    doc_ref = db.collection(USER_STATES_COLLECTION).document(user_id)
    update_data = {'state': state}
    if data is not None:
        update_data['data'] = data
    else: # ถ้าไม่ได้ส่ง data มา ให้ลบ data เก่าออก หรือตั้งเป็นค่าว่าง
        update_data['data'] = {} 
    
    doc_ref.set(update_data, merge=True) # merge=True เพื่อรวมข้อมูล ไม่ใช่เขียนทับทั้งหมด
    print(f"User {user_id} state updated to: {state}")

def save_diagnosis_record(user_id, record_data):
    """บันทึกข้อมูลการวินิจฉัยที่สมบูรณ์ลงใน Firestore."""
    if db is None:
        print("Firestore is not initialized. Cannot save diagnosis record.")
        return
    
    # เพิ่ม timestamp เข้าไปในข้อมูล
    record_data['timestamp'] = firestore.SERVER_TIMESTAMP # ใช้ Server Timestamp ของ Firestore
    record_data['user_id'] = user_id # เพิ่ม user_id เข้าไปใน record
    
    db.collection(DIAGNOSES_COLLECTION).add(record_data)
    print(f"Diagnosis record saved for user {user_id}")
    
# ----------------------------------------------------------------------
# 4. ฟังก์ชันสำหรับการรับ Webhook จาก LINE
# ----------------------------------------------------------------------
# Cloud Functions จะรับ Request object มาตรงๆ
def main(request): # เปลี่ยนชื่อฟังก์ชันจาก callback เป็น main
    # Cloud Functions จะจัดการ Request body และ headers ให้
    # ดึงค่า X-Line-Signature จาก Header
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)

    # Log Request body (สำหรับ Debugging ใน Cloud Logging)
    print("Request body: " + body)

    # ถ้าเป็น GET Request (สำหรับการ Verify Webhook)
    if request.method == 'GET':
        print("Received GET request to /callback (for verification).")
        return 'OK', 200 # ตอบกลับ 200 OK ทันที

    # ถ้าเป็น POST Request (สำหรับ LINE Event จริงๆ)
    try:
        # ประมวลผล Webhook Event โดยใช้ Line Webhook Handler
        # handler.handle จะเรียกฟังก์ชัน handle_text_message หรือ handle_image_message
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/channel secret or Webhook URL.")
        # ใน Cloud Functions เราจะ return Response object แทน abort
        return "Invalid signature", 400
    except Exception as e:
        print(f"Error handling webhook event: {e}")
        return "Internal Server Error", 500 # ตอบกลับ Error 500 ถ้ามีปัญหาอื่น

    return 'OK', 200 # ตอบกลับ LINE ว่าได้รับ Request แล้ว

# ----------------------------------------------------------------------
# 5. ฟังก์ชันจัดการข้อความ Text Message
# ----------------------------------------------------------------------
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = event.source.user_id # ดึง User ID ของผู้ใช้
    user_state = get_user_state(user_id) # ดึงสถานะปัจจุบันของผู้ใช้

    text_message = event.message.text.lower() # แปลงข้อความเป็นตัวพิมพ์เล็กเพื่อการเปรียบเทียบ
    reply_text = "" # ข้อความตอบกลับเริ่มต้น

    # --- ตรวจสอบคำถามอาการเบื้องต้นทั่วไปก่อน (ใหม่!) ---
    for symptom, details in common_symptoms_treatments.items():
        if symptom in text_message: # ตรวจสอบว่าอาการอยู่ในข้อความหรือไม่
            reply_text = (
                f"**💡 วิธีรักษาเบื้องต้นสำหรับอาการ{symptom}:**\n"
                f"{details['treatment']}\n\n"
                f"**⚠️ คำเตือนสำคัญ:**\n"
                f"{details['warning']}\n\n"
                f"ข้อมูลนี้เป็นเพียงคำแนะนำเบื้องต้นจากระบบ AI และไม่สามารถใช้แทนการวินิจฉัยของแพทย์ได้\n"
                f"เพื่อการวินิจฉัยที่ถูกต้องและแม่นยำที่สุด **โปรดปรึกษาแพทย์ผู้เชี่ยวชาญ** หรือผู้เชี่ยวชาญด้านสุขภาพ"
            )
            line_bot_api.reply_message(
                event.reply_token,
                TextMessage(text=reply_text)
            )
            return # หยุดการทำงานเมื่อพบอาการและตอบกลับแล้ว

    # --- ตรวจสอบสถานะการสนทนา (สำหรับข้อมูลจากรูปภาพ) ---
    if user_state['state'] == 'waiting_for_location':
        # ผู้ใช้ตอบคำถามตำแหน่งของอาการ
        diagnosis_data = user_state.get('data', {})
        diagnosis_data['location'] = event.message.text # บันทึกตำแหน่งที่ผู้ใช้ส่งมา

        update_user_state(user_id, 'waiting_for_other_symptoms', diagnosis_data)
        reply_text = "ขอบคุณสำหรับข้อมูลตำแหน่งครับ\nมีอาการอื่นๆ ร่วมด้วยไหมครับ? (เช่น คัน, ปวด, มีไข้, บวมแดง, ผื่นขึ้น) หากไม่มีให้พิมพ์ 'ไม่มี' ครับ"
    
    elif user_state['state'] == 'waiting_for_other_symptoms':
        # ผู้ใช้ตอบคำถามอาการอื่นๆ
        diagnosis_data = user_state.get('data', {})
        other_symptoms = event.message.text.strip()
        if other_symptoms.lower() == 'ไม่มี':
            diagnosis_data['other_symptoms'] = 'ไม่มี'
        else:
            diagnosis_data['other_symptoms'] = other_symptoms

        # บันทึกข้อมูลการวินิจฉัยที่สมบูรณ์ลง Firestore
        save_diagnosis_record(user_id, diagnosis_data)
        
        # รีเซ็ตสถานะเป็น idle และล้างข้อมูลชั่วคราว
        update_user_state(user_id, 'idle', {}) 
        reply_text = "ขอบคุณสำหรับข้อมูลครับ ข้อมูลของคุณถูกบันทึกไว้เพื่อเป็นประโยชน์ต่อไป\nหากต้องการวิเคราะห์รูปภาพอีกครั้ง ส่งรูปมาได้เลยนะครับ!"

    else: # สถานะ 'idle' หรือสถานะอื่นๆ ที่ไม่เกี่ยวข้องกับการสนทนาต่อเนื่อง
        # โค้ดสำหรับตอบข้อความทั่วไปเหมือนเดิม
        if "สวัสดี" in text_message or "hi" in text_message:
            reply_text = "สวัสดีครับ คุณหมอ AI ยินดีให้บริการครับ! 👋\nส่งรูปภาพผิวหนังหรือบาดแผลมาให้ผมช่วยวิเคราะห์เบื้องต้นได้เลยนะครับ"
        elif "คืออะไร" in text_message or "ทำอะไรได้" in text_message:
            reply_text = "ผมคือ AI สำหรับวิเคราะห์รูปภาพโรคผิวหนังและบาดแผลเบื้องต้นครับ\nเพียงแค่ส่งรูปภาพเข้ามา ผมจะช่วยวิเคราะห์โรคของคุณจากภาพที่ส่งมา"
        elif "ขอบคุณ" in text_message:
            reply_text = "ยินดีครับ หากมีคำถามหรือต้องการให้ช่วยวิเคราะห์อีก ส่งรูปมาได้เลยนะครับ!"
        else:
            reply_text = "ผมยังไม่เข้าใจคำถามครับ โปรดส่งรูปภาพเพื่อให้ผมช่วยวิเคราะห์เบื้องต้นครับ 😊"

    # ตอบกลับผู้ใช้ด้วยข้อความ (เฉพาะกรณีที่ยังไม่ได้ตอบจากอาการเบื้องต้น)
    line_bot_api.reply_message(
        event.reply_token,
        TextMessage(text=reply_text)
    )

# ----------------------------------------------------------------------
# 6. ฟังก์ชันจัดการรูปภาพ (Image Message)
# ----------------------------------------------------------------------
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = event.source.user_id # ดึง User ID ของผู้ใช้

    if interpreter is None:
        line_bot_api.reply_message(
            event.reply_token,
            TextMessage(text="ขออภัยครับ เราไม่เข้าใจคำถาม")
        )
        return

    message_content = line_bot_api.get_message_content(event.message.id)
    image_bytes = io.BytesIO(message_content.content)

    try:
        # Preprocess image
        img = Image.open(image_bytes).convert('RGB')
        img = img.resize((224, 224))
        img_array = np.array(img)
        img_array = img_array / 255.0
        img_array = np.expand_dims(img_array, axis=0)

        # Predict ด้วย TFLite Interpreter
        interpreter.set_tensor(input_details[0]['index'], img_array.astype(input_details[0]['dtype']))
        interpreter.invoke()
        predictions = interpreter.get_tensor(output_details[0]['index'])
        
        predicted_class_index = np.argmax(predictions[0])
        predicted_class_english_name = class_names[predicted_class_index] # ได้ชื่อภาษาอังกฤษจากโมเดล
        confidence = np.max(predictions[0])

        # ค้นหาชื่อภาษาไทยที่เกี่ยวข้อง
        predicted_class_thai_name = ""
        for item in class_names_map:
            if item['english'] == predicted_class_english_name:
                predicted_class_thai_name = item['thai']
                break
        
        # ถ้าหาชื่อไทยไม่เจอ ให้ใช้ชื่ออังกฤษแทน
        if not predicted_class_thai_name:
            predicted_class_thai_name = predicted_class_english_name

        # ดึงข้อมูลเพิ่มเติมจาก class_details (ใช้ชื่อภาษาอังกฤษเป็น Key)
        details = class_details.get(predicted_class_english_name, {})
        treatment_info = details.get('treatment', 'ไม่มีข้อมูลวิธีรักษาเบื้องต้น')
        avoid_info = details.get('avoid', 'ไม่มีข้อมูลสิ่งที่ควรหลีกเลี่ยง')
        severe_warning_info = details.get('severe_warning', 'ไม่มีคำเตือนสำหรับอาการรุนแรง')

        # สร้างข้อความตอบกลับที่สมบูรณ์ขึ้น
        reply_text = (
            f"จากการวิเคราะห์เบื้องต้น AI คาดการณ์ว่ารูปภาพนี้มีลักษณะคล้ายกับ:\n"
            f"**{predicted_class_thai_name} ({predicted_class_english_name})**\n" # แสดงทั้งไทยและอังกฤษ
            f"(ความมั่นใจ: {confidence:.2f})\n\n"
            f"**💡 วิธีรักษาเบื้องต้น:**\n"
            f"{treatment_info}\n\n"
            f"**🚫 สิ่งที่ควรหลีกเลี่ยง:**\n"
            f"{avoid_info}\n\n"
            f"**🚨 หากอาการรุนแรง/ผิดปกติ:**\n"
            f"{severe_warning_info}\n\n"
            f"**⚠️ คำเตือนสำคัญ:**\n"
            f"ข้อมูลนี้เป็นเพียงการวิเคราะห์เบื้องต้นจากระบบ AI และไม่สามารถใช้แทนการวินิจฉัยของแพทย์ได้\n"
            f"เพื่อการวินิจฉัยที่ถูกต้องและแม่นยำที่สุด **โปรดปรึกษาแพทย์ผู้เชี่ยวชาญ** หรือผู้เชี่ยวชาญด้านสุขภาพ"
        )
        
        # บันทึกข้อมูลการวินิจฉัยเบื้องต้นลงใน Firestore ชั่วคราว
        # เพื่อรอข้อมูลเพิ่มเติมจากผู้ใช้
        temp_diagnosis_data = {
            'predicted_class_english': predicted_class_english_name,
            'predicted_class_thai': predicted_class_thai_name,
            'confidence': float(confidence) # แปลงเป็น float ปกติก่อนบันทึก
        }
        update_user_state(user_id, 'waiting_for_location', temp_diagnosis_data)

        # ตอบกลับผู้ใช้ด้วยข้อความผลการวิเคราะห์ และถามคำถามแรก
        line_bot_api.reply_message(
            event.reply_token,
            TextMessage(text=reply_text + "\n\n**เพื่อบันทึกข้อมูลเพิ่มเติม:**\nอาการนี้เกิดขึ้นที่ส่วนไหนของร่างกายครับ/คะ? (เช่น แขน, ขา, ใบหน้า, ลำตัว)")
        )
        return # ออกจากฟังก์ชันหลังจากตอบและเปลี่ยนสถานะ

    except Exception as e:
        reply_text = f"ขออภัยครับ เกิดข้อผิดพลาดในการประมวลผลรูปภาพ: {e}\nโปรดลองอีกครั้งหรือส่งรูปภาพที่ชัดเจนขึ้น"
        print(f"Error processing image: {e}")

    line_bot_api.reply_message(
        event.reply_token,
        TextMessage(text=reply_text)
    )

# ไม่ต้องมี if __name__ == "__main__": ใน Cloud Functions
