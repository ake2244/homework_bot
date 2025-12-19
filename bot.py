import asyncio
import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import config

# Инициализация
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Хранение данных в памяти (без БД)
assignments = []  # список заданий
user_answers = {}  # ответы пользователей
subscribed_users = set()  # подписанные пользователи
waiting_for_text_answer = {}  # кто ждет текстового ответа {user_id: assignment_id}

# Состояния для FSM
class AddAssignment(StatesGroup):
    waiting_for_assignment = State()
    waiting_for_assignment_type = State()

# ============ КОМАНДЫ АДМИНА ============
@dp.message(Command("add"))
async def add_assignment(message: types.Message, state: FSMContext):
    """Добавить новое задание"""
    if message.from_user.id != config.ADMIN_ID:
        return
    
    # Создаем клавиатуру для выбора типа задания
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="С вариантами ответов")],
            [types.KeyboardButton(text="Текстовый ответ")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await message.answer("Выберите тип задания:", reply_markup=keyboard)
    await state.set_state(AddAssignment.waiting_for_assignment_type)

@dp.message(AddAssignment.waiting_for_assignment_type)
async def choose_assignment_type(message: types.Message, state: FSMContext):
    """Обработка выбора типа задания"""
    assignment_type = "choice" if "вариантами" in message.text else "text"
    await state.update_data(assignment_type=assignment_type)
    
    if assignment_type == "choice":
        await message.answer(
            "📝 Отправьте задание с вариантами ответов в формате:\n\n"
            "ВОПРОС: Сколько будет 2+2?\n"
            "A) 3\n"
            "B) 4\n"
            "C) 5\n"
            "D) 6\n"
            "ПРАВИЛЬНЫЙ ОТВЕТ: B\n"
            "ОБЪЯСНЕНИЕ: 2+2=4",
            reply_markup=types.ReplyKeyboardRemove()
        )
    else:
        await message.answer(
            "📝 Отправьте текстовое задание в формате:\n\n"
            "ВОПРОС: Напишите столицу Франции\n"
            "ПРАВИЛЬНЫЙ ОТВЕТ: Париж\n"
            "ОБЪЯСНЕНИЕ: Париж - столица Франции",
            reply_markup=types.ReplyKeyboardRemove()
        )
    
    await state.set_state(AddAssignment.waiting_for_assignment)

@dp.message(AddAssignment.waiting_for_assignment)
async def process_assignment(message: types.Message, state: FSMContext):
    """Обработка присланного задания - УПРОЩЕННАЯ ВЕРСИЯ"""
    try:
        data = await state.get_data()
        assignment_type = data.get('assignment_type', 'choice')
        
        text = message.text
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        question = ""
        options = {}
        correct_answer = ""
        explanation = ""
        
        for line in lines:
            if line.lower().startswith('вопрос:'):
                question = line[7:].strip()
            elif line.lower().startswith('правильный ответ:'):
                correct_answer = line[17:].strip()
            elif line.lower().startswith('объяснение:'):
                explanation = line[11:].strip()
            elif assignment_type == 'choice' and ') ' in line:
                # Обрабатываем варианты: "A) 3"
                parts = line.split(') ', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    options[key] = value
        
        # Проверяем заполненность
        if not question:
            await message.answer("❌ Не найден вопрос. Начните строку с 'ВОПРОС:'")
            await state.clear()
            return
        
        if not correct_answer:
            await message.answer("❌ Не найден правильный ответ. Начните строку с 'ПРАВИЛЬНЫЙ ОТВЕТ:'")
            await state.clear()
            return
        
        if assignment_type == 'choice' and not options:
            await message.answer("❌ Не найдены варианты ответов. Добавьте варианты в формате 'A) текст'")
            await state.clear()
            return
        
        # Создаем задание
        assignment = {
            'id': len(assignments) + 1,
            'type': assignment_type,
            'question': question,
            'correct_answer': correct_answer,
            'explanation': explanation,
            'sent': False,
            'date': datetime.datetime.now()
        }
        
        if assignment_type == 'choice':
            assignment['options'] = options
        
        assignments.append(assignment)
        
        # Подтверждение
        preview = f"✅ Задание #{assignment['id']} добавлено!\n\n"
        preview += f"Тип: {'С вариантами' if assignment_type == 'choice' else 'Текстовое'}\n"
        preview += f"Вопрос: {question}\n"
        
        if assignment_type == 'choice':
            preview += f"Варианты: {', '.join([f'{k})' for k in options.keys()])}\n"
        
        preview += f"Правильный ответ: {correct_answer}\n"
        
        if explanation:
            preview += f"Объяснение: {explanation[:50]}..."
        
        await message.answer(preview)
        await state.clear()
        
        # Отладка
        print(f"Добавлено задание: {assignment}")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}\n\nПопробуйте еще раз.")
        await state.clear()

@dp.message(Command("list"))
async def list_assignments(message: types.Message):
    """Показать все задания"""
    if message.from_user.id != config.ADMIN_ID:
        return
    
    if not assignments:
        await message.answer("📭 Нет заданий")
        return
    
    text = "📋 Список заданий:\n\n"
    for assign in assignments:
        status = "✅ Отправлено" if assign['sent'] else "⏳ Ожидает"
        type_icon = "📝" if assign['type'] == 'text' else "🔘"
        text += f"{type_icon} #{assign['id']}: {status}\n"
        text += f"   Вопрос: {assign['question'][:50]}...\n"
        if assign['type'] == 'choice' and assign.get('options'):
            text += f"   Варианты: {', '.join(assign['options'].keys())}\n"
        text += f"   Правильный ответ: {assign['correct_answer']}\n\n"
    
    await message.answer(text)

@dp.message(Command("stats"))
async def show_stats(message: types.Message):
    """Детальная статистика ответов по пользователям"""
    if message.from_user.id != config.ADMIN_ID:
        return
    
    if not user_answers:
        await message.answer("📊 Еще нет ответов")
        return
    
    text = "📊 ДЕТАЛЬНАЯ СТАТИСТИКА\n\n"
    
    # 1. Общая статистика по заданиям
    text += "📋 ОБЩАЯ СТАТИСТИКА:\n"
    total_correct = 0
    total_answers = 0
    
    for assign_id, answers in user_answers.items():
        assign = next((a for a in assignments if a['id'] == assign_id), None)
        if assign:
            correct = sum(1 for ans in answers.values() if ans['is_correct'])
            total = len(answers)
            total_correct += correct
            total_answers += total
            
            type_icon = "📝" if assign['type'] == 'text' else "🔘"
            percentage = (correct/total*100) if total > 0 else 0
            
            text += f"{type_icon} Задание #{assign_id}:\n"
            text += f"   📝 {assign['question'][:40]}...\n"
            text += f"   ✅ {correct}/{total} правильных ({percentage:.1f}%)\n\n"
    
    # Общий процент
    total_percentage = (total_correct/total_answers*100) if total_answers > 0 else 0
    text += f"📈 ИТОГО: {total_correct}/{total_answers} ({total_percentage:.1f}%)\n\n"
    
    # 2. Статистика по каждому пользователю
    text += "👥 СТАТИСТИКА ПО ПОЛЬЗОВАТЕЛЯМ:\n\n"
    
    # Собираем всех пользователей, которые когда-либо отвечали
    all_users = set()
    for answers in user_answers.values():
        all_users.update(answers.keys())
    
    if not all_users:
        await message.answer(text)
        return
    
    # Для каждого пользователя
    for user_id in all_users:
        user_correct = 0
        user_total = 0
        user_details = []
        
        # Считаем ответы пользователя
        for assign_id, answers in user_answers.items():
            if user_id in answers:
                user_total += 1
                if answers[user_id]['is_correct']:
                    user_correct += 1
                
                assign = next((a for a in assignments if a['id'] == assign_id), None)
                if assign:
                    status = "✅" if answers[user_id]['is_correct'] else "❌"
                    user_details.append(f"   {status} #{assign_id}: {answers[user_id]['answer']}")
        
        # Процент пользователя
        user_percentage = (user_correct/user_total*100) if user_total > 0 else 0
        
        # Добавляем в статистику
        text += f"👤 Пользователь ID: {user_id}\n"
        text += f"   📊 {user_correct}/{user_total} правильных ({user_percentage:.1f}%)\n"
        
        # Показываем детали только если ответов немного
        if user_total <= 5:
            for detail in user_details:
                text += f"{detail}\n"
        
        text += "\n"
    
    # 3. Таблица прогресса
    text += "📅 ТАБЛИЦА ПРОГРЕССА:\n\n"
    
    # Заголовок таблицы
    header = "ID пользователя | "
    for assign_id in sorted(user_answers.keys()):
        header += f"#{assign_id} | "
    text += header + "\n"
    
    # Разделитель
    text += "-" * (len(header) + 10) + "\n"
    
    # Данные для каждого пользователя
    for user_id in all_users:
        row = f"{user_id:13} | "
        for assign_id in sorted(user_answers.keys()):
            if user_id in user_answers[assign_id]:
                answer = user_answers[assign_id][user_id]
                row += "✅ " if answer['is_correct'] else "❌ "
            else:
                row += "➖ "
            row += "| "
        text += row + "\n"
    
    # Если текст слишком длинный, разбиваем на несколько сообщений
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for i, part in enumerate(parts):
            await message.answer(f"📄 Часть {i+1}/{len(parts)}:\n\n{part}")
    else:
        await message.answer(text)

@dp.message(Command("stats_short"))
async def show_stats_short(message: types.Message):
    """Краткая статистика по пользователям"""
    if message.from_user.id != config.ADMIN_ID:
        return
    
    if not user_answers:
        await message.answer("📊 Еще нет ответов")
        return
    
    text = "📊 КРАТКАЯ СТАТИСТИКА ПО ПОЛЬЗОВАТЕЛЯМ\n\n"
    
    # Собираем всех пользователей
    all_users = set()
    for answers in user_answers.values():
        all_users.update(answers.keys())
    
    # Сортируем пользователей по проценту правильных ответов
    users_stats = []
    for user_id in all_users:
        user_correct = 0
        user_total = 0
        
        for answers in user_answers.values():
            if user_id in answers:
                user_total += 1
                if answers[user_id]['is_correct']:
                    user_correct += 1
        
        percentage = (user_correct/user_total*100) if user_total > 0 else 0
        users_stats.append({
            'user_id': user_id,
            'correct': user_correct,
            'total': user_total,
            'percentage': percentage
        })
    
    # Сортируем по проценту (по убыванию)
    users_stats.sort(key=lambda x: x['percentage'], reverse=True)
    
    # Выводим рейтинг
    for i, stats in enumerate(users_stats):
        medal = "🥇" if i == 0 else ("🥈" if i == 1 else ("🥉" if i == 2 else "🔢"))
        text += f"{medal} {i+1}. Пользователь {stats['user_id']}:\n"
        text += f"   📊 {stats['correct']}/{stats['total']} ({stats['percentage']:.1f}%)\n\n"
    
    # Общая статистика
    total_correct = sum(stats['correct'] for stats in users_stats)
    total_answers = sum(stats['total'] for stats in users_stats)
    total_percentage = (total_correct/total_answers*100) if total_answers > 0 else 0
    
    text += f"📈 ИТОГО по всем пользователям:\n"
    text += f"   ✅ {total_correct}/{total_answers} ({total_percentage:.1f}%)"
    
    await message.answer(text)

@dp.message(Command("user_stats"))
async def user_stats_command(message: types.Message):
    """Статистика по конкретному пользователю"""
    if message.from_user.id != config.ADMIN_ID:
        return
    
    # Ожидаем ID пользователя
    args = message.text.split()
    if len(args) < 2:
        await message.answer("ℹ️ Использование: /user_stats [ID_пользователя]\nПример: /user_stats 123456789")
        return
    
    try:
        target_user_id = int(args[1])
    except ValueError:
        await message.answer("❌ Неверный формат ID. ID должен быть числом.")
        return
    
    if not user_answers:
        await message.answer(f"📭 Пользователь {target_user_id} еще не отвечал на задания")
        return
    
    # Проверяем, есть ли ответы от этого пользователя
    user_has_answers = any(target_user_id in answers for answers in user_answers.values())
    
    if not user_has_answers:
        await message.answer(f"📭 Пользователь {target_user_id} еще не отвечал на задания")
        return
    
    # Собираем статистику
    text = f"📊 СТАТИСТИКА ПОЛЬЗОВАТЕЛЯ {target_user_id}\n\n"
    
    user_correct = 0
    user_total = 0
    user_details = []
    
    for assign_id, answers in user_answers.items():
        if target_user_id in answers:
            user_total += 1
            answer_data = answers[target_user_id]
            assign = next((a for a in assignments if a['id'] == assign_id), None)
            
            if assign:
                if answer_data['is_correct']:
                    user_correct += 1
                    status = "✅"
                else:
                    status = "❌"
                
                # Детали по каждому заданию
                detail = f"{status} Задание #{assign_id}:\n"
                detail += f"   📝 {assign['question'][:60]}...\n"
                
                if assign['type'] == 'choice' and assign.get('options'):
                    user_answer = answer_data['answer']
                    answer_text = assign['options'].get(user_answer, user_answer)
                    detail += f"   🤔 Ваш ответ: {user_answer}) {answer_text}\n"
                else:
                    detail += f"   🤔 Ваш ответ: {answer_data['answer']}\n"
                
                detail += f"   ✅ Правильный ответ: {assign['correct_answer']}\n"
                
                if not answer_data['is_correct'] and assign.get('explanation'):
                    detail += f"   💡 Объяснение: {assign['explanation'][:100]}...\n"
                
                user_details.append(detail)
    
    # Общая статистика пользователя
    user_percentage = (user_correct/user_total*100) if user_total > 0 else 0
    
    text += f"📈 ОБЩАЯ СТАТИСТИКА:\n"
    text += f"   ✅ Правильных: {user_correct}/{user_total}\n"
    text += f"   📊 Процент: {user_percentage:.1f}%\n\n"
    
    text += f"📝 ДЕТАЛИ ОТВЕТОВ:\n\n"
    
    # Добавляем детали по каждому заданию
    for detail in user_details:
        text += detail + "\n"
    
    # Если текст слишком длинный
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for i, part in enumerate(parts):
            await message.answer(f"📄 Часть {i+1}/{len(parts)}:\n\n{part}")
    else:
        await message.answer(text)

@dp.message(Command("progress"))
async def show_progress_table(message: types.Message):
    """Таблица успеваемости всех пользователей"""
    if message.from_user.id != config.ADMIN_ID:
        return
    
    if not user_answers:
        await message.answer("📭 Еще нет ответов")
        return
    
    # Собираем всех пользователей
    all_users = set()
    for answers in user_answers.values():
        all_users.update(answers.keys())
    
    if not all_users:
        await message.answer("📭 Нет пользователей с ответами")
        return
    
    text = "📊 ТАБЛИЦА УСПЕВАЕМОСТИ\n\n"
    
    # Заголовок с номерами заданий
    assignments_sorted = sorted(user_answers.keys())
    
    # Первая строка - заголовок
    header = "👤 Пользователь | Всего | %  | "
    for assign_id in assignments_sorted:
        header += f"#{assign_id} | "
    text += header + "\n"
    
    # Разделительная линия
    text += "-" * len(header) + "\n"
    
    # Собираем статистику по каждому пользователю
    users_data = []
    for user_id in all_users:
        user_row = {}
        user_correct = 0
        user_total = 0
        
        for assign_id in assignments_sorted:
            if user_id in user_answers.get(assign_id, {}):
                user_total += 1
                answer = user_answers[assign_id][user_id]
                if answer['is_correct']:
                    user_correct += 1
                    user_row[assign_id] = "✅"
                else:
                    user_row[assign_id] = "❌"
            else:
                user_row[assign_id] = "—"
        
        user_percentage = (user_correct/user_total*100) if user_total > 0 else 0
        
        users_data.append({
            'user_id': user_id,
            'correct': user_correct,
            'total': user_total,
            'percentage': user_percentage,
            'row': user_row
        })
    
    # Сортируем по проценту (по убыванию)
    users_data.sort(key=lambda x: x['percentage'], reverse=True)
    
    # Выводим строки таблицы
    for user_data in users_data:
        # Строка пользователя
        row = f"{user_data['user_id']:13} | "
        row += f"{user_data['correct']:2}/{user_data['total']:2} | "
        row += f"{user_data['percentage']:4.1f}% | "
        
        for assign_id in assignments_sorted:
            row += f"{user_data['row'][assign_id]:2} | "
        
        text += row + "\n"
    
    # Итоговая строка
    text += "-" * len(header) + "\n"
    
    # Процент выполнения по каждому заданию
    bottom_row = "✅ % выполнения  |       |    | "
    for assign_id in assignments_sorted:
        answers = user_answers.get(assign_id, {})
        if answers:
            correct = sum(1 for a in answers.values() if a['is_correct'])
            total = len(answers)
            percentage = (correct/total*100) if total > 0 else 0
            bottom_row += f"{percentage:3.0f}% | "
        else:
            bottom_row += " —  | "
    
    text += bottom_row
    
    await message.answer(f"```\n{text}\n```", parse_mode="Markdown")

@dp.message(Command("debug"))
async def show_debug(message: types.Message):
    """Отладочная информация"""
    if message.from_user.id != config.ADMIN_ID:
        return
    
    text = f"🤖 Отладочная информация:\n\n"
    text += f"Всего заданий: {len(assignments)}\n"
    text += f"Подписчиков: {len(subscribed_users)}\n"
    text += f"Ответов сохранено: {len(user_answers)}\n\n"
    
    if assignments:
        text += "Последнее задание:\n"
        last = assignments[-1]
        text += f"ID: {last['id']}\n"
        text += f"Тип: {last['type']}\n"
        text += f"Вопрос: {last['question']}\n"
        text += f"Ответ: {last['correct_answer']}\n"
    
    await message.answer(text)

# ============ КОМАНДЫ ПОЛЬЗОВАТЕЛЕЙ ============
@dp.message(Command("start"))
async def start_command(message: types.Message):
    """Начало работы"""
    user_id = message.from_user.id
    subscribed_users.add(user_id)
    
    await message.answer(
        "👋 Привет! Я бот для заданий.\n\n"
        "📅 Я буду присылать задания по понедельникам, средам и пятницам в 00:00.\n\n"
        "🔘 Задания с вариантами - выбирайте кнопкой\n"
        "📝 Текстовые задания - пишите ответ сообщением"
    )
    print(f"Пользователь {user_id} подписался")

@dp.message(Command("answer"))
async def force_answer(message: types.Message):
    """Принудительная отправка задания (для теста)"""
    if message.from_user.id != config.ADMIN_ID:
        return
    
    await message.answer("Отправляю задание...")
    await send_assignment_to_all()

# ============ ОТПРАВКА ЗАДАНИЙ ============
async def send_assignment_to_all():
    """Отправить задание всем подписанным пользователям"""
    # Находим первое неотправленное задание
    assignment = next((a for a in assignments if not a['sent']), None)
    
    if not assignment:
        print("❌ Нет заданий для отправки")
        return
    
    print(f"📤 Отправляем задание #{assignment['id']}: {assignment['question'][:50]}...")
    
    # Отправляем всем пользователям
    sent_count = 0
    for user_id in list(subscribed_users):  # Используем копию списка
        try:
            if assignment['type'] == 'choice':
                # Создаем клавиатуру с вариантами
                buttons = []
                for key, value in assignment['options'].items():
                    callback_data = f"answer_{assignment['id']}_{key}"
                    buttons.append(
                        [types.InlineKeyboardButton(
                            text=f"{key}) {value}",
                            callback_data=callback_data
                        )]
                    )
                
                keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
                
                message_text = f"📚 Задание #{assignment['id']} (с вариантами):\n\n{assignment['question']}"
                await bot.send_message(user_id, message_text, reply_markup=keyboard)
                
            else:
                # Текстовое задание без кнопок
                message_text = f"📚 Задание #{assignment['id']} (текстовое):\n\n{assignment['question']}\n\n✏️ Напишите ответ текстом в чат"
                await bot.send_message(user_id, message_text)
                
                # Помечаем, что пользователь должен ответить
                waiting_for_text_answer[user_id] = assignment['id']
            
            sent_count += 1
            print(f"   ✓ Отправлено пользователю {user_id}")
                
        except Exception as e:
            print(f"   ✗ Ошибка отправки пользователю {user_id}: {e}")
            # Удаляем из подписчиков если не получается отправить
            if user_id in subscribed_users:
                subscribed_users.remove(user_id)
    
    # Помечаем как отправленное
    assignment['sent'] = True
    print(f"✅ Задание #{assignment['id']} отправлено {sent_count} пользователям")

# ============ ОБРАБОТКА ОТВЕТОВ ============
@dp.callback_query(lambda c: c.data.startswith("answer_"))
async def handle_choice_answer(callback: types.CallbackQuery):
    """Обработка выбранного ответа для заданий с вариантами"""
    user_id = callback.from_user.id
    _, assign_id, answer = callback.data.split("_")
    assign_id = int(assign_id)
    
    # Находим задание
    assignment = next((a for a in assignments if a['id'] == assign_id), None)
    if not assignment or assignment['type'] != 'choice':
        await callback.answer("Задание не найдено")
        return
    
    # Проверяем ответ
    is_correct = (answer == assignment['correct_answer'])
    
    # Сохраняем ответ
    if assign_id not in user_answers:
        user_answers[assign_id] = {}
    
    user_answers[assign_id][user_id] = {
        'answer': answer,
        'is_correct': is_correct,
        'time': datetime.datetime.now().isoformat()
    }
    
    # Отправляем результат
    if is_correct:
        await callback.message.edit_text(
            f"✅ Правильно!\n\n"
            f"Задание #{assignment['id']}\n"
            f"Ваш ответ: {answer}) {assignment['options'][answer]}"
        )
    else:
        correct_key = assignment['correct_answer']
        correct_value = assignment['options'][correct_key]
        
        await callback.message.edit_text(
            f"❌ Неправильно\n\n"
            f"Задание #{assignment['id']}\n"
            f"Ваш ответ: {answer}) {assignment['options'].get(answer, '?')}\n"
            f"Правильный ответ: {correct_key}) {correct_value}\n\n"
            f"💡 Объяснение: {assignment['explanation']}"
        )
    
    await callback.answer()

@dp.message()
async def handle_text_answer(message: types.Message):
    """Обработка текстовых ответов"""
    user_id = message.from_user.id
    
    # Проверяем, ожидаем ли мы текстовый ответ от этого пользователя
    if user_id in waiting_for_text_answer:
        assign_id = waiting_for_text_answer[user_id]
        
        # Находим задание
        assignment = next((a for a in assignments if a['id'] == assign_id), None)
        if not assignment or assignment['type'] != 'text':
            del waiting_for_text_answer[user_id]
            return
        
        # Получаем ответ пользователя
        user_answer = message.text.strip().lower()
        correct_answer = assignment['correct_answer'].lower()
        
        # Простая проверка
        is_correct = (user_answer == correct_answer)
        
        # Сохраняем ответ
        if assign_id not in user_answers:
            user_answers[assign_id] = {}
        
        user_answers[assign_id][user_id] = {
            'answer': user_answer,
            'is_correct': is_correct,
            'time': datetime.datetime.now().isoformat()
        }
        
        # Отправляем результат
        if is_correct:
            await message.answer(
                f"✅ Правильно!\n\n"
                f"Задание #{assignment['id']}\n"
                f"Ваш ответ: {user_answer}\n\n"
                f"💡 {assignment['explanation']}"
            )
        else:
            await message.answer(
                f"❌ Неправильно\n\n"
                f"Задание #{assignment['id']}\n"
                f"Ваш ответ: {user_answer}\n"
                f"Правильный ответ: {correct_answer}\n\n"
                f"💡 Объяснение: {assignment['explanation']}"
            )
        
        # Удаляем из ожидающих ответа
        del waiting_for_text_answer[user_id]

# ============ ПЛАНИРОВЩИК ============
def start_scheduler():
    """Запуск планировщика для отправки по расписанию"""
    scheduler = AsyncIOScheduler()
    
    # Проверяем, что мы на сервере (нет DISPLAY)
    import os
    if 'DISPLAY' not in os.environ:
        scheduler.add_job(
            send_assignment_to_all,
            'cron',
            day_of_week='mon,wed,fri',
            hour=0,
            minute=0,
            timezone='Europe/Moscow'
        )
        scheduler.start()
        print("📅 Планировщик запущен: Пн, Ср, Пт в 00:00")
    else:
        print("⚠️ Планировщик не запущен (локальная разработка)")

# ============ ЗАПУСК БОТА ============
async def main():
    """Основная функция запуска"""
    print("🤖 Бот запускается...")
    
    try:
        # Запускаем планировщик
        start_scheduler()
        
        # Запускаем бота
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")

# Это должно быть В КОНЦЕ ФАЙЛА, ВНЕ ВСЕХ ФУНКЦИЙ:
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")