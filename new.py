"""
بوت آل بصيص المُطوّر - إصدار 2.0
بوت متكامل لإدارة الاستبيانات والأسئلة في مجموعات تليجرام
يجمع بين أفضل ميزات البوتات السابقة مع تحسينات جديدة
"""

import logging
import json
import os
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

# --- إعداد التسجيل والمتغيرات العامة ---

# إعداد التسجيل للمساعدة في تتبع الأخطاء
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot_log.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# حالات المحادثة
# حالات إنشاء السؤال
ASK_QUESTION, ASK_OPTIONS, ASK_GROUP_IDS_CREATE = range(3)
# حالات إدارة الأسئلة
MANAGE_LIST_QUESTIONS, SELECT_MANAGE_ACTION, ASK_SHARE_GROUP_ID, CONFIRM_DELETE = range(3, 7)
# حالات عرض الإجابات
SELECT_QUESTION = 7

# قاموس لحفظ الأسئلة وإجابات الطلاب
questions_db = {}  # سيخزن {question_id: {'question': text, 'options': [], 'answers': {user_id: {'answer': answer, 'name': name, 'username': username}}}}
question_counter = 1  # عداد للأسئلة يبدأ من 1

# معرفات المشرفين المسموح لهم باستخدام البوت (يمكن إضافة معرفات أو أرقام)
ALLOWED_USERS = [1687347144]  # معرفات رقمية
ALLOWED_USERNAMES = ["memovq", "omr_taher", "Mohameddammar"]  # معرفات نصية

# --- وظائف إدارة البيانات ---

def is_authorized(user):
    """التحقق من صلاحيات المستخدم بناءً على المعرف الرقمي أو اسم المستخدم."""
    # التحقق من المعرف الرقمي
    if user.id in ALLOWED_USERS:
        return True
    
    # التحقق من اسم المستخدم
    if user.username and user.username.lower() in [name.lower() for name in ALLOWED_USERNAMES]:
        return True
    
    return False

async def unauthorized_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رسالة للمستخدمين غير المصرح لهم."""
    if update.message:
        await update.message.reply_text("عذرًا، لا تمتلك صلاحيات لاستخدام هذا الأمر.")
    elif update.callback_query:
        try:
            await update.callback_query.answer("عذرًا، لا تمتلك صلاحيات لهذا الإجراء.", show_alert=True)
        except TelegramError as e:
            logger.warning(f"Could not answer callback query for unauthorized access: {e}")
    
    return ConversationHandler.END

def save_data():
    """حفظ البيانات في ملف JSON."""
    global questions_db, question_counter
    data = {
        'questions_db': questions_db,
        'question_counter': question_counter,
        'last_saved': datetime.datetime.now().isoformat()
    }
    
    # إنشاء نسخة احتياطية قبل الحفظ
    if os.path.exists('quiz_data.json'):
        try:
            os.rename('quiz_data.json', f'quiz_data_backup_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
        except Exception as e:
            logger.error(f"خطأ في إنشاء نسخة احتياطية: {e}")
    
    # حفظ البيانات
    try:
        with open('quiz_data.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info("تم حفظ البيانات بنجاح")
        return True
    except Exception as e:
        logger.error(f"خطأ في حفظ البيانات: {e}")
        return False

def load_data():
    """تحميل البيانات من ملف JSON."""
    global questions_db, question_counter
    
    # التحقق من وجود ملف البيانات
    if os.path.exists('quiz_data.json'):
        try:
            with open('quiz_data.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                questions_db = data.get('questions_db', {})
                question_counter = data.get('question_counter', 1)
            logger.info(f"تم تحميل البيانات بنجاح. عدد الأسئلة: {len(questions_db)}, المعرف التالي: {question_counter}")
            return True
        except Exception as e:
            logger.error(f"حدث خطأ أثناء تحميل البيانات: {e}")
            questions_db = {}
            question_counter = 1
            return False
    else:
        logger.info("ملف البيانات غير موجود، سيتم إنشاء بيانات جديدة")
        questions_db = {}
        question_counter = 1
        return True

def renumber_questions():
    """إعادة ترقيم الأسئلة بالتسلسل وحذف الفجوات."""
    global questions_db, question_counter
    
    if not questions_db:
        question_counter = 1
        return
    
    # إنشاء قاموس جديد بترقيم متسلسل
    new_questions_db = {}
    sorted_questions = sorted(questions_db.items(), key=lambda x: int(x[0]))
    
    # إعادة ترقيم الأسئلة
    for i, (_, question_data) in enumerate(sorted_questions, 1):
        new_questions_db[str(i)] = question_data
    
    # تحديث قاموس الأسئلة وعداد الأسئلة
    questions_db = new_questions_db
    question_counter = len(questions_db) + 1
    
    # حفظ التغييرات
    save_data()
    logger.info(f"تم إعادة ترقيم الأسئلة. عدد الأسئلة الآن: {len(questions_db)}")

async def _generate_question_list_markup(callback_prefix: str):
    """إنشاء لوحة مفاتيح بقائمة الأسئلة مع بادئة callback محددة."""
    if not questions_db:
        return None, "لا توجد أسئلة مسجلة حتى الآن."

    keyboard = []
    # فرز الأسئلة حسب المعرف الرقمي
    sorted_q_ids = sorted(questions_db.keys(), key=int)

    for q_id in sorted_q_ids:
        q_data = questions_db[q_id]
        short_question = q_data['question'][:30] + "..." if len(q_data['question']) > 30 else q_data['question']
        keyboard.append([InlineKeyboardButton(f"سؤال {q_id}: {short_question}", callback_data=f"{callback_prefix}:{q_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    return reply_markup, "اختر السؤال المطلوب:"

# --- وظائف إنشاء سؤال جديد ---

async def ask_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يبدأ عملية إنشاء سؤال جديد."""
    user = update.message.from_user
    if not is_authorized(user):
        return await unauthorized_access(update, context)

    await update.message.reply_text("ما السؤال الذي تودّ طرحه على الطلاب؟")
    # تنظيف بيانات المستخدم القديمة
    context.user_data.clear()
    return ASK_QUESTION

async def ask_question_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل نص السؤال."""
    global question_counter
    
    context.user_data['new_question_text'] = update.message.text
    context.user_data['options'] = []

    await update.message.reply_text("الآن، أدخل جميع الإجابات المحتملة (كل إجابة في رسالة منفصلة). \nعند الانتهاء، استخدم /done.")
    return ASK_OPTIONS

async def receive_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل خيارات الإجابة."""
    option = update.message.text.strip() # إزالة المسافات الزائدة
    if option: # التأكد من أن الخيار ليس فارغاً
        context.user_data.setdefault('options', []).append(option) # طريقة آمنة للإضافة للقائمة
        await update.message.reply_text(f"أُضيفت الإجابة: {option}")
    else:
        await update.message.reply_text("لا يمكن إضافة خيار فارغ.")
    return ASK_OPTIONS # البقاء في نفس الحالة لاستقبال المزيد

async def done_adding_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ينهي إضافة الخيارات وينتقل لطلب معرفات المجموعات."""
    if not context.user_data.get('options'):
        await update.message.reply_text("لم تقم بإدخال أي إجابات! الرجاء إدخال إجابة واحدة على الأقل أو استخدم /cancel.")
        return ASK_OPTIONS # البقاء في نفس الحالة

    await update.message.reply_text("أُضيفت كل الإجابات بنجاح.\n\nالآن أرسل مُعرفات المجموعات التي تود نشر الرسالة بها (كل معرف في رسالة منفصلة، يجب أن يبدأ بـ -):")
    context.user_data['group_ids'] = []
    return ASK_GROUP_IDS_CREATE

async def receive_group_ids_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل معرفات المجموعات لإنشاء السؤال."""
    group_id = update.message.text.strip()
    # تحقق بسيط من أن المعرف قد يكون صالحًا (رقمي ويبدأ بـ - للمجموعات)
    if group_id.startswith('-') and group_id[1:].isdigit():
        context.user_data.setdefault('group_ids', []).append(group_id)
        await update.message.reply_text(f"أُضيف مُعرف المجموعة: {group_id}\n\nإن انتهيت، أرسل السؤال للمجموعات باستخدام /send.")
    else:
        await update.message.reply_text(f"'{group_id}' ليس معرف مجموعة صالح. يجب أن يكون رقمًا ويبدأ بـ '-'. حاول مرة أخرى أو استخدم /send إذا انتهيت.")
    return ASK_GROUP_IDS_CREATE # البقاء في نفس الحالة

async def send_new_question_to_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ينشئ السؤال في قاعدة البيانات ويرسله للمجموعات المحددة."""
    global question_counter, questions_db

    group_ids = context.user_data.get('group_ids', [])
    question_text = context.user_data.get('new_question_text')
    options = context.user_data.get('options', [])

    if not group_ids:
        await update.message.reply_text("لم تقم بإدخال أي معرفات مجموعات! الرجاء إدخال معرف واحد على الأقل أو استخدم /cancel.")
        return ASK_GROUP_IDS_CREATE

    if not question_text or not options:
         await update.message.reply_text("حدث خطأ، معلومات السؤال غير مكتملة. الرجاء البدء من جديد بـ /ask.")
         context.user_data.clear() # تنظيف البيانات عند الخطأ
         return ConversationHandler.END

    # إنشاء معرف فريد للسؤال الآن فقط
    current_question_id = str(question_counter)
    question_counter += 1

    # تخزين السؤال في قاعدة البيانات
    questions_db[current_question_id] = {
        'question': question_text,
        'options': options,
        'answers': {} # يبدأ فارغاً
    }
    
    # حفظ البيانات بعد إضافة السؤال
    save_data()
    
    logger.info(f"Question {current_question_id} created: {questions_db[current_question_id]}")

    # إنشاء أزرار بمعرفات فريدة تتضمن معرف السؤال والإجابة
    keyboard = []
    for option in options:
        # إنشاء callback_data تتضمن معرف السؤال والخيار
        callback_data = f"ans:{current_question_id}:{option}" # تمييز callback الإجابة
        keyboard.append([InlineKeyboardButton(option, callback_data=callback_data)])
    reply_markup = InlineKeyboardMarkup(keyboard)

    send_errors = []
    # إرسال السؤال والأزرار إلى كل مجموعة تم إدخال معرفها
    for group_id in group_ids:
        try:
            # إرسال السؤال بدون رقم السؤال للطلاب
            await context.bot.send_message(
                chat_id=group_id,
                text=f"{question_text}", # النص الأصلي للسؤال فقط
                reply_markup=reply_markup
            )
            logger.info(f"Question {current_question_id} sent to group {group_id}")
        except TelegramError as e:
            logger.error(f"Error sending Q{current_question_id} to group {group_id}: {e}", exc_info=True)
            send_errors.append(group_id)
        except Exception as e: # التقاط أي أخطاء أخرى
            logger.error(f"Unexpected error sending Q{current_question_id} to group {group_id}: {e}", exc_info=True)
            send_errors.append(group_id)

    # رسالة واحدة للمستخدم تلخص النتيجة
    if not send_errors:
         final_message = f"✅ تم تسجيل السؤال برقم: {current_question_id}\n" \
                         f"وتم إرساله بنجاح إلى {len(group_ids)} مجموعة/مجموعات."
    else:
         final_message = f"⚠️ تم تسجيل السؤال برقم: {current_question_id}\n" \
                         f"لكن حدثت مشكلة في الإرسال لـ {len(send_errors)} من أصل {len(group_ids)} مجموعة.\n" \
                         f"المجموعات التي فشل الإرسال إليها: {', '.join(send_errors)}"

    await update.message.reply_text(final_message)
    context.user_data.clear() # تنظيف بيانات المستخدم بعد الانتهاء
    return ConversationHandler.END

# --- وظائف استقبال إجابات الطلاب ---

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل إجابة الطالب عند النقر على زر."""
    query = update.callback_query
    user = query.from_user
    
    # استخراج المعلومات من البيانات
    try:
        parts = query.data.split(":", 2)
        if len(parts) != 3 or parts[0] != "ans":
            await query.answer("صيغة البيانات غير صحيحة.")
            return
        
        prefix, question_id, answer = parts
    except Exception as e:
        logger.error(f"Error parsing answer callback: {e}")
        await query.answer("حدث خطأ في معالجة الإجابة.")
        return
    
    # التحقق من وجود السؤال
    if question_id not in questions_db:
        await query.answer("هذا السؤال لم يعد متاحًا.")
        logger.warning(f"User {user.id} tried to answer non-existent question {question_id}")
        return
    
    # التحقق مما إذا كان الطالب قد أجاب مسبقًا على هذا السؤال
    if str(user.id) in questions_db[question_id]['answers']:
        old_answer = questions_db[question_id]['answers'][str(user.id)]['answer']
        await query.answer(f"سبق أن أجبت على هذا السؤال. إجابتك السابقة: {old_answer}")
        return
    
    # تسجيل الإجابة مع معلومات المستخدم
    questions_db[question_id]['answers'][str(user.id)] = {
        'answer': answer,
        'name': user.first_name or "مستخدم",
        'username': user.username or "غير متوفر",
        'timestamp': datetime.datetime.now().isoformat()
    }
    
    # حفظ البيانات بعد كل إجابة جديدة
    save_data()
    
    # تأكيد للمستخدم
    await query.answer(f"تم تسجيل إجابتك: {answer}")
    logger.info(f"User {user.id} ({user.username or 'no username'}) answered Q{question_id}: {answer}")

# --- وظائف عرض إجابات الأسئلة (/answers) ---

async def list_questions_for_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض قائمة بالأسئلة لاختيار سؤال وعرض إجاباته."""
    user = update.message.from_user
    if not is_authorized(user):
        return await unauthorized_access(update, context)
    
    reply_markup, message_text = await _generate_question_list_markup(callback_prefix="show_ans")
    
    if not reply_markup:
        await update.message.reply_text(message_text) # رسالة "لا توجد أسئلة"
        return ConversationHandler.END
        
    await update.message.reply_text("اختر السؤال الذي تريد عرض إجاباته:", reply_markup=reply_markup)
    return SELECT_QUESTION

async def show_question_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض إحصائيات وتفاصيل الإجابات لسؤال محدد."""
    query = update.callback_query
    
    if not is_authorized(query.from_user):
        return await unauthorized_access(update, context)
    
    await query.answer() # رد على الكويري
    
    # استخراج معرف السؤال
    try:
        prefix, question_id = query.data.split(':', 1)
        if prefix != "show_ans":
            logger.warning(f"Ignored answers callback with wrong prefix: {query.data}")
            await query.edit_message_text("حدث خطأ في معالجة البيانات.")
            return ConversationHandler.END
    except ValueError:
        logger.error(f"Invalid show_answers callback data format: {query.data}")
        await query.edit_message_text("حدث خطأ في صيغة البيانات.")
        return ConversationHandler.END
    
    # التحقق من وجود السؤال
    if question_id not in questions_db:
        await query.edit_message_text("هذا السؤال غير موجود (ربما تم حذفه).")
        return ConversationHandler.END
    
    question_data = questions_db[question_id]
    question_text = question_data['question']
    answers_dict = question_data['answers']
    
    # التحقق من وجود إجابات
    if not answers_dict:
        try:
            await query.edit_message_text(f"📊 *السؤال {question_id}:*\n_{question_text}_\n\n-- لا توجد إجابات لهذا السؤال حتى الآن --", parse_mode=ParseMode.MARKDOWN)
        except TelegramError as e:
            logger.warning(f"Could not edit message for Q{question_id} with no answers: {e}")
        return ConversationHandler.END
    
    # --- حساب الإحصائيات ---
    stats = {option: 0 for option in question_data['options']} # تهيئة العدادات لكل الخيارات
    total_answers = len(answers_dict)
    
    for user_data in answers_dict.values():
        answer = user_data.get('answer')
        if answer in stats:
            stats[answer] += 1
        else:
            # هذا الخيار لم يعد موجودًا أو إجابة غير متوقعة
            logger.warning(f"Answer '{answer}' found for Q{question_id} but not in options {question_data['options']}")
            stats[answer] = stats.get(answer, 0) + 1 # نضيفه للإحصاء
    
    stats_lines = []
    # فرز الخيارات حسب النص الأصلي
    sorted_options = question_data['options']
    for option in sorted_options:
        count = stats.get(option, 0) # نحصل على العدد من القاموس
        percentage = (count / total_answers) * 100 if total_answers > 0 else 0
        stats_lines.append(f" - {option}: {count} ({percentage:.1f}%)")
    
    # إضافة أي إجابات غير متوقعة وجدت
    for option, count in stats.items():
        if option not in sorted_options:
            percentage = (count / total_answers) * 100 if total_answers > 0 else 0
            stats_lines.append(f" - [غير متوقع] {option}: {count} ({percentage:.1f}%)")
    
    stats_text = "\n".join(stats_lines)
    
    # --- إعداد نص الإجابات التفصيلية ---
    answers_details = []
    # فرز الإجابات حسب اسم المستخدم
    sorted_user_ids = sorted(answers_dict.keys(), key=lambda uid: answers_dict[uid].get('name', '').lower())
    
    for uid in sorted_user_ids:
        user_data = answers_dict[uid]
        name = user_data.get('name', 'مستخدم')
        username = user_data.get('username', 'غير متوفر')
        answer = user_data.get('answer', 'غير معروفة')
        timestamp = user_data.get('timestamp', '')
        
        # تنسيق الوقت إذا كان متوفرًا
        time_str = ""
        if timestamp:
            try:
                dt = datetime.datetime.fromisoformat(timestamp)
                time_str = f" ({dt.strftime('%Y-%m-%d %H:%M')})"
            except:
                pass
                
        answers_details.append(f"{name} (@{username}){time_str}: {answer}")
    
    answers_text = "\n".join(answers_details)
    
    # --- إنشاء النص النهائي ---
    result_text = f"📊 *السؤال {question_id}:*\n_{question_text}_\n\n"
    result_text += f"👥 *عدد الإجابات:* {total_answers}\n\n"
    result_text += f"📈 *الإحصائيات:*\n{stats_text}\n\n"
    result_text += f"📝 *الإجابات التفصيلية:*\n{answers_text}"
    
    # التحقق من طول الرسالة
    if len(result_text) > 4000:  # تيليجرام يحد طول الرسالة
        short_result = f"📊 *السؤال {question_id}:*\n_{question_text}_\n\n"
        short_result += f"👥 *عدد الإجابات:* {total_answers}\n\n"
        short_result += f"📈 *الإحصائيات:*\n{stats_text}\n\n"
        short_result += f"⚠️ _الإجابات كثيرة جدًا للعرض هنا. يمكنك تصدير البيانات باستخدام_ /export"
        
        try:
            await query.edit_message_text(short_result, parse_mode=ParseMode.MARKDOWN)
        except TelegramError as e:
            logger.error(f"Error sending long answer stats for Q{question_id}: {e}")
            # محاولة إرسال بدون تنسيق إذا فشل الماركداون
            await query.edit_message_text(
                f"السؤال {question_id}: {question_text}\n\n"
                f"عدد الإجابات: {total_answers}\n\n"
                f"الإحصائيات:\n{stats_text}\n\n"
                f"الإجابات كثيرة جدًا للعرض هنا."
            )
    else:
        try:
            await query.edit_message_text(result_text, parse_mode=ParseMode.MARKDOWN)
        except TelegramError as e:
            logger.error(f"Error sending answer stats for Q{question_id}: {e}")
            # محاولة إرسال بدون تنسيق
            await query.edit_message_text(
                f"السؤال {question_id}: {question_text}\n\n"
                f"عدد الإجابات: {total_answers}\n\n"
                f"الإحصائيات:\n{stats_text}\n\n"
                f"الإجابات التفصيلية:\n{answers_text}"
            )
    
    return ConversationHandler.END

# --- وظائف إدارة الأسئلة (/list) ---

async def list_questions_manage_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يبدأ محادثة إدارة الأسئلة بعرض القائمة."""
    user = update.message.from_user
    if not is_authorized(user):
        return await unauthorized_access(update, context)

    reply_markup, message_text = await _generate_question_list_markup(callback_prefix="m_select")

    if not reply_markup:
        await update.message.reply_text(message_text) # رسالة "لا توجد أسئلة"
        return ConversationHandler.END # لا أسئلة للإدارة

    await update.message.reply_text("اختر السؤال الذي تريد إدارته:", reply_markup=reply_markup)
    # تنظيف أي بيانات إدارة سابقة
    context.user_data.pop('manage_question_id', None)
    return MANAGE_LIST_QUESTIONS

async def show_question_manage_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض خيارات الإدارة (مشاركة، حذف، عودة) لسؤال محدد."""
    query = update.callback_query
    # لا داعي للتحقق من الصلاحية هنا، فالدخول للمحادثة يتطلب صلاحية

    await query.answer() # رد على الكويري

    try:
        prefix, question_id = query.data.split(':', 1)
        if prefix != "m_select":
             logger.warning(f"Ignored manage callback with wrong prefix: {query.data}")
             # العودة لحالة الانتظار لاختيار سؤال
             reply_markup, message_text = await _generate_question_list_markup(callback_prefix="m_select")
             if reply_markup:
                 await query.edit_message_text(message_text, reply_markup=reply_markup)
             else:
                 await query.edit_message_text(message_text) # لا توجد أسئلة الآن
                 return ConversationHandler.END
             return MANAGE_LIST_QUESTIONS
    except ValueError:
        logger.error(f"Invalid manage select callback data format: {query.data}")
        try:
            await query.edit_message_text("حدث خطأ في البيانات.")
        except TelegramError as e: logger.warning(f"Could not edit msg on bad m_select callback: {e}")
        return ConversationHandler.END

    if question_id not in questions_db:
        try:
            await query.edit_message_text("هذا السؤال غير موجود (ربما تم حذفه). الرجاء الاختيار مجددًا:")
        except TelegramError as e: logger.warning(f"Could not edit msg for deleted Q in manage: {e}")
        # الرجوع للقائمة المحدثة
        reply_markup, message_text = await _generate_question_list_markup(callback_prefix="m_select")
        if reply_markup:
            # يجب إرسال رسالة جديدة لأن edit قد تفشل إذا الرسالة الأصلية حذفت مثلاً
            await query.message.reply_text(message_text, reply_markup=reply_markup)
            return MANAGE_LIST_QUESTIONS
        else:
            await query.message.reply_text(message_text) # لا توجد أسئلة الآن
            return ConversationHandler.END

    context.user_data['manage_question_id'] = question_id
    question_text = questions_db[question_id]['question']

    keyboard = [
        [InlineKeyboardButton("↪️ مشاركة السؤال مجددًا", callback_data=f"m_share:{question_id}")],
        [InlineKeyboardButton("🗑️ حذف السؤال", callback_data=f"m_delete:{question_id}")],
        [InlineKeyboardButton("⬅️ العودة إلى القائمة", callback_data="m_back_list")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(
            f"*إدارة السؤال {question_id}:*\n_{question_text}_\n\n"
            f"اختر الإجراء المطلوب:", 
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except TelegramError as e:
        logger.error(f"Error editing message in show_question_manage_options for Q{question_id}: {e}")
        # محاولة إرسال رسالة جديدة كبديل
        try:
             await query.message.reply_text(
                f"*إدارة السؤال {question_id}:*\n_{question_text}_\n\n"
                f"اختر الإجراء المطلوب:", 
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except TelegramError as inner_e:
             logger.error(f"Failed to send fallback message in show_question_manage_options: {inner_e}")

    return SELECT_MANAGE_ACTION

async def prompt_share_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يطلب معرف المجموعة لمشاركة السؤال فيها."""
    query = update.callback_query
    await query.answer()

    question_id = context.user_data.get('manage_question_id')
    if not question_id or question_id not in questions_db:
         try:
             await query.edit_message_text("حدث خطأ أو تم حذف السؤال. الرجاء البدء من /list.")
         except TelegramError as e: logger.warning(f"Could not edit message on missing Q in prompt_share: {e}")
         return ConversationHandler.END

    try:
        await query.edit_message_text(f"أرسل *معرف المجموعة* التي تريد إعادة نشر السؤال {question_id} فيها (يجب أن يبدأ بـ '-'):\nأو استخدم /cancel للإلغاء.", parse_mode=ParseMode.MARKDOWN)
    except TelegramError as e:
        logger.warning(f"Could not edit message in prompt_share_group_id: {e}")
        # إرسال رسالة جديدة إذا فشل التعديل
        await query.message.reply_text(f"أرسل *معرف المجموعة* التي تريد إعادة نشر السؤال {question_id} فيها (يجب أن يبدأ بـ '-'):\nأو استخدم /cancel للإلغاء.", parse_mode=ParseMode.MARKDOWN)

    return ASK_SHARE_GROUP_ID

async def share_question_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل معرف المجموعة ويعيد نشر السؤال المحدد."""
    group_id_input = update.message.text.strip()
    question_id = context.user_data.get('manage_question_id')
    admin_user_id = update.message.from_user.id

    if not question_id or question_id not in questions_db:
        await update.message.reply_text("لم يتم العثور على السؤال المحدد للإرسال. الرجاء البدء من /list.")
        return ConversationHandler.END

    if not (group_id_input.startswith('-') and group_id_input[1:].isdigit()):
         await update.message.reply_text(f"'{group_id_input}' ليس معرف مجموعة صالح. يجب أن يكون رقمًا ويبدأ بـ '-'.\n\nأرسل المعرف الصحيح أو استخدم /cancel.")
         return ASK_SHARE_GROUP_ID # يبقى في نفس الحالة لطلب المعرف مجدداً

    group_id = group_id_input
    question_data = questions_db[question_id]
    question_text = question_data['question']
    options = question_data['options']

    # إعادة إنشاء الأزرار بنفس الـ callback data لضمان تسجيل الإجابات بشكل صحيح
    keyboard = []
    for option in options:
        callback_data = f"ans:{question_id}:{option}" # استخدام نفس التنسيق الأصلي
        keyboard.append([InlineKeyboardButton(option, callback_data=callback_data)])
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await context.bot.send_message(
            chat_id=group_id,
            text=f"{question_text}", # نفس نص السؤال
            reply_markup=reply_markup
        )
        await update.message.reply_text(f"✅ تم إعادة إرسال السؤال {question_id} إلى المجموعة: {group_id}")
        logger.info(f"Admin {admin_user_id} reshared question {question_id} to group {group_id}")
        return ConversationHandler.END
    except TelegramError as e:
        logger.error(f"Error sharing question {question_id} to group {group_id}: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ حدث خطأ أثناء إرسال السؤال إلى المجموعة {group_id}. تأكد أن البوت عضو ومشرف في المجموعة.\n\nيمكنك محاولة إرسال المعرف مرة أخرى أو استخدام /cancel.")
        return ASK_SHARE_GROUP_ID # البقاء في نفس الحالة لإعادة المحاولة
    except Exception as e:
         logger.error(f"Unexpected error sharing question {question_id} to group {group_id}: {e}", exc_info=True)
         await update.message.reply_text(f"⚠️ حدث خطأ غير متوقع أثناء الإرسال للمجموعة {group_id}. حاول مرة أخرى أو استخدم /cancel.")
         return ASK_SHARE_GROUP_ID


async def prompt_delete_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض رسالة تأكيد قبل حذف السؤال."""
    query = update.callback_query
    await query.answer()

    question_id = context.user_data.get('manage_question_id')
    if not question_id or question_id not in questions_db:
         try:
            await query.edit_message_text("حدث خطأ أو تم حذف السؤال بالفعل. الرجاء البدء من /list.")
         except TelegramError as e: logger.warning(f"Could not edit msg on missing Q in prompt_delete: {e}")
         return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("‼️ نعم، احذف السؤال", callback_data=f"m_delete_confirm:{question_id}")],
        [InlineKeyboardButton("❌ إلغاء الحذف", callback_data=f"m_delete_cancel:{question_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(
            f"🚨 *تحذير:* هل أنت متأكد أنك تريد حذف السؤال *{question_id}* وكل إجاباته؟\n\n"
            f"_{questions_db[question_id]['question']}_\n\n"
            f"*لا يمكن التراجع عن هذا الإجراء!*", 
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except TelegramError as e:
         logger.warning(f"Could not edit message in prompt_delete_confirmation: {e}")
         # ارسال رسالة جديدة كبديل
         await query.message.reply_text(
            f"🚨 *تحذير:* هل أنت متأكد أنك تريد حذف السؤال *{question_id}* وكل إجاباته؟\n\n"
            f"_{questions_db[question_id]['question']}_\n\n"
            f"*لا يمكن التراجع عن هذا الإجراء!*", 
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

    return CONFIRM_DELETE

async def delete_question_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يحذف السؤال بعد التأكيد."""
    query = update.callback_query
    admin_user_id = query.from_user.id

    await query.answer("جاري الحذف...")

    try:
        prefix, question_id_from_callback = query.data.split(':', 1)
        if prefix != "m_delete_confirm":
             logger.warning(f"Ignored delete confirm callback with wrong prefix: {query.data}")
             return CONFIRM_DELETE
    except ValueError:
        logger.error(f"Invalid delete confirm callback data format: {query.data}")
        try:
            await query.edit_message_text("حدث خطأ في البيانات.")
        except TelegramError as e: logger.warning(f"Could not edit message on bad delete confirm data: {e}")
        return ConversationHandler.END

    # الحصول على معرف السؤال من محادثة المستخدم
    question_id = context.user_data.get('manage_question_id')
    
    # التحقق من تطابق المعرفين
    if question_id != question_id_from_callback:
        logger.error(f"Question ID mismatch in delete: user_data={question_id}, callback={question_id_from_callback}")
        try:
            await query.edit_message_text("حدث خطأ في تطابق بيانات السؤال.")
        except TelegramError as e: logger.warning(f"Could not edit message on Q ID mismatch: {e}")
        return ConversationHandler.END

    # التحقق من وجود السؤال
    if question_id not in questions_db:
        try:
            await query.edit_message_text("هذا السؤال غير موجود أو تم حذفه بالفعل.")
        except TelegramError as e: logger.warning(f"Could not edit message for already deleted Q: {e}")
        return ConversationHandler.END

    # حفظ معلومات السؤال للتأكيد
    deleted_question_text = questions_db[question_id]['question']
    answer_count = len(questions_db[question_id]['answers'])
    
    # حذف السؤال
    deleted_question = questions_db.pop(question_id, None)
    # حفظ التغييرات فوراً
    save_data()
    
    logger.info(f"Admin {admin_user_id} deleted question {question_id}")
    
    # تنظيف بيانات المستخدم
    context.user_data.pop('manage_question_id', None)
    
    try:
        await query.edit_message_text(
            f"✅ تم حذف السؤال {question_id} بنجاح.\n\n"
            f"السؤال المحذوف: {deleted_question_text}\n"
            f"عدد الإجابات المحذوفة: {answer_count}"
        )
    except TelegramError as e:
        logger.warning(f"Could not edit message after delete: {e}")
        # محاولة إرسال رسالة جديدة
        await query.message.reply_text(
            f"✅ تم حذف السؤال {question_id} بنجاح.\n\n"
            f"السؤال المحذوف: {deleted_question_text}\n"
            f"عدد الإجابات المحذوفة: {answer_count}"
        )
    
    return ConversationHandler.END

async def cancel_delete_back_to_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يلغي عملية الحذف ويعود لقائمة خيارات إدارة السؤال."""
    query = update.callback_query
    await query.answer("تم إلغاء الحذف")

    try:
        prefix, question_id = query.data.split(':', 1)
        if prefix != "m_delete_cancel":
            logger.warning(f"Ignored delete cancel callback with wrong prefix: {query.data}")
            return CONFIRM_DELETE
    except ValueError:
        logger.error(f"Invalid delete cancel callback data format: {query.data}")
        return ConversationHandler.END

    if question_id not in questions_db:
        await query.edit_message_text("هذا السؤال غير موجود (ربما تم حذفه). الرجاء البدء من /list.")
        return ConversationHandler.END

    # العودة لعرض خيارات إدارة السؤال
    question_text = questions_db[question_id]['question']
    
    keyboard = [
        [InlineKeyboardButton("↪️ مشاركة السؤال مجددًا", callback_data=f"m_share:{question_id}")],
        [InlineKeyboardButton("🗑️ حذف السؤال", callback_data=f"m_delete:{question_id}")],
        [InlineKeyboardButton("⬅️ العودة إلى القائمة", callback_data="m_back_list")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(
            f"*إدارة السؤال {question_id}:*\n_{question_text}_\n\n"
            f"اختر الإجراء المطلوب:", 
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except TelegramError as e:
        logger.warning(f"Could not edit message in cancel_delete: {e}")
        await query.message.reply_text(
            f"*إدارة السؤال {question_id}:*\n_{question_text}_\n\n"
            f"اختر الإجراء المطلوب:", 
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    return SELECT_MANAGE_ACTION

async def back_to_manage_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعود إلى قائمة الأسئلة الرئيسية للإدارة."""
    query = update.callback_query
    await query.answer()
    
    # تنظيف معرف السؤال الحالي
    context.user_data.pop('manage_question_id', None)
    
    # إنشاء قائمة محدثة بالأسئلة
    reply_markup, message_text = await _generate_question_list_markup(callback_prefix="m_select")
    
    if not reply_markup:
        await query.edit_message_text(message_text) # رسالة "لا توجد أسئلة"
        return ConversationHandler.END
    
    await query.edit_message_text("اختر السؤال الذي تريد إدارته:", reply_markup=reply_markup)
    return MANAGE_LIST_QUESTIONS

# --- وظائف إضافية مفيدة ---

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تصدير بيانات الأسئلة والإجابات كملف JSON."""
    user = update.message.from_user
    if not is_authorized(user):
        return await unauthorized_access(update, context)
    
    if not questions_db:
        await update.message.reply_text("لا توجد بيانات للتصدير حاليًا.")
        return
    
    # إنشاء نسخة من البيانات للتصدير
    export_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    export_filename = f"quiz_export_{export_time}.json"
    
    try:
        # إضافة معلومات إحصائية للتصدير
        export_data = {
            "questions_db": questions_db,
            "metadata": {
                "exported_at": datetime.datetime.now().isoformat(),
                "exported_by": f"{user.first_name} (@{user.username})" if user.username else f"{user.first_name} (ID: {user.id})",
                "total_questions": len(questions_db),
                "question_counter": question_counter
            }
        }
        
        # حفظ البيانات في ملف مؤقت
        with open(export_filename, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=4)
        
        # إرسال الملف للمستخدم
        with open(export_filename, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=export_filename,
                caption=f"تصدير بيانات بوت آل بصيص\nعدد الأسئلة: {len(questions_db)}\nتاريخ التصدير: {export_time}"
            )
        
        # حذف الملف المؤقت
        try:
            os.remove(export_filename)
        except:
            pass
            
        logger.info(f"User {user.id} exported quiz data with {len(questions_db)} questions")
        
    except Exception as e:
        logger.error(f"Error exporting data: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ حدث خطأ أثناء تصدير البيانات: {e}")

async def fix_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعادة ترقيم الأسئلة وإصلاح قاعدة البيانات."""
    user = update.message.from_user
    if not is_authorized(user):
        return await unauthorized_access(update, context)
    
    await update.message.reply_text("جاري إعادة ترقيم الأسئلة وإصلاح قاعدة البيانات...")
    
    old_count = len(questions_db)
    old_ids = set(questions_db.keys())
    
    # إعادة ترقيم الأسئلة
    renumber_questions()
    
    new_count = len(questions_db)
    new_ids = set(questions_db.keys())
    
    await update.message.reply_text(
        f"✅ تم إصلاح قاعدة البيانات بنجاح.\n\n"
        f"عدد الأسئلة: {new_count}\n"
        f"ترقيم الأسئلة الجديد: {', '.join(sorted(new_ids, key=int))}\n\n"
        f"تم حفظ البيانات بنجاح."
    )

# --- وظائف عامة ---

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء المحادثة الحالية."""
    if update.message:
        await update.message.reply_text("تم إلغاء العملية الحالية.")
    elif update.callback_query:
        await update.callback_query.answer("تم إلغاء العملية")
        try:
            await update.callback_query.edit_message_text("تم إلغاء العملية الحالية.")
        except TelegramError:
            pass
    
    # تنظيف بيانات المستخدم في الحالة
    if context.user_data:
        context.user_data.clear()
        
    logger.info(f"User {update.effective_user.id} cancelled conversation")
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض رسالة الترحيب والأوامر المتاحة."""
    user = update.message.from_user
    
    if not is_authorized(user):
        await update.message.reply_text(
            "مرحبًا بك في بوت آل بصيص. عذرًا، لا تمتلك صلاحيات لاستخدام هذا البوت.\n"
            "إذا كنت تعتقد أن هذا خطأ، يرجى التواصل مع مدير البوت."
        )
        return
    
    await update.message.reply_text(
        f"أهلاً {user.first_name}! مرحبًا بك في بوت آل بصيص المُطور 🌟\n\n"
        "الأوامر المتوفرة:\n"
        "◾️ /ask - إنشاء سؤال جديد\n"
        "◾️ /list - عرض الأسئلة وإدارتها (مشاركة/حذف)\n"
        "◾️ /answers - عرض إجابات الطلاب\n"
        "◾️ /cancel - لإلغاء العملية الحالية\n"
        "◾️ /fix - إصلاح وإعادة ترقيم قاعدة البيانات\n"
        "◾️ /export - تصدير بيانات الأسئلة والإجابات\n"
    )

def main():
    """النقطة الرئيسية للبوت."""
    # تحميل البيانات المحفوظة
    load_data()
    
    # ضع رمز API الخاص بك هنا - يفضل حفظه في ملف بيئة منفصل
    TOKEN = "8061858990:AAHyXoyccZAJvLVpbL9ENEFGDxf7gpmZQnc"
    
    # بناء التطبيق
    app = ApplicationBuilder().token(TOKEN).build()
    
    # --- ConversationHandler لإنشاء سؤال جديد (/ask) ---
    create_question_handler = ConversationHandler(
        entry_points=[CommandHandler('ask', ask_question_start)],
        states={
            ASK_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_question_received)],
            ASK_OPTIONS: [
                CommandHandler('done', done_adding_options),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_options),
            ],
            ASK_GROUP_IDS_CREATE: [
                CommandHandler('send', send_new_question_to_groups),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group_ids_create),
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # --- ConversationHandler لعرض الإجابات (/answers) ---
    answers_handler = ConversationHandler(
        entry_points=[CommandHandler('answers', list_questions_for_answers)],
        states={
            SELECT_QUESTION: [CallbackQueryHandler(show_question_answers, pattern=r"^show_ans:")]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # --- ConversationHandler لإدارة الأسئلة (/list) ---
    manage_questions_handler = ConversationHandler(
        entry_points=[CommandHandler('list', list_questions_manage_start)],
        states={
            MANAGE_LIST_QUESTIONS: [CallbackQueryHandler(show_question_manage_options, pattern=r"^m_select:")],
            SELECT_MANAGE_ACTION: [
                CallbackQueryHandler(prompt_share_group_id, pattern=r"^m_share:"),
                CallbackQueryHandler(prompt_delete_confirmation, pattern=r"^m_delete:"),
                CallbackQueryHandler(back_to_manage_list, pattern=r"^m_back_list$")
            ],
            ASK_SHARE_GROUP_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, share_question_to_group)],
            CONFIRM_DELETE: [
                CallbackQueryHandler(delete_question_confirmed, pattern=r"^m_delete_confirm:"),
                CallbackQueryHandler(cancel_delete_back_to_options, pattern=r"^m_delete_cancel:")
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # --- ربط الأوامر العامة ---
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("export", export_data))
    app.add_handler(CommandHandler("fix", fix_database))
    
    # --- ربط محادثات البوت ---
    app.add_handler(create_question_handler)  # محادثة إنشاء سؤال
    app.add_handler(answers_handler)          # محادثة عرض الإجابات
    app.add_handler(manage_questions_handler) # محادثة إدارة الأسئلة
    
    # --- استقبال إجابات الطلاب ---
    app.add_handler(CallbackQueryHandler(receive_answer, pattern=r"^ans:"))
    
    # --- معالج إلغاء عام إضافي ---
    app.add_handler(CommandHandler('cancel', cancel))
    
    # تشغيل البوت
    logger.info("Starting bot...")
    app.run_polling()
    logger.info("Bot stopped.")

if __name__ == "__main__":
    main()
