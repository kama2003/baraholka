import asyncio
import logging
import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.utils import executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# === Настройки ===
TOKEN = "8196226068:AAFfDnp_V3B2E_wGXZVWPbj7grLDwursigc"
DB_URL = "postgresql://postgres:UCVsjmKonvErYVabRPtVOOVvbQHQbAAj@postgres.railway.internal:5432/railway"
db_pool = None

# Классы состояний для добавления, поиска и редактирования объявления
class AddProduct(StatesGroup):
    name = State()
    category = State()
    price = State()
    contact = State()
    photo = State()  # Новый шаг для загрузки фотографии

class SearchState(StatesGroup):
    by_name = State()

class EditProduct(StatesGroup):
    choosing_field = State()
    waiting_for_input = State()

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DB_URL)

async def get_db():
    return db_pool

# Основное меню
kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Разместить объявление"), KeyboardButton(text="🔍 Найти")],
        [KeyboardButton(text="📜 Все товары"), KeyboardButton(text="🧾 Мои объявления")]
    ],
    resize_keyboard=True
)

@dp.message(F.text == "/start")
async def start(message: types.Message):
    await message.answer("👋 Добро пожаловать! Выберите действие:", reply_markup=kb)

# --- Добавление объявления ---
@dp.message(F.text == "➕ Разместить объявление")
async def start_add_product(message: types.Message, state: FSMContext):
    await state.set_state(AddProduct.name)
    await message.answer("📦 Введите *название* товара:", parse_mode="Markdown")

@dp.message(AddProduct.name)
async def step_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT category FROM products ORDER BY category")
    if not rows:
        return await message.answer("❌ Нет категорий в базе. Сначала добавьте категорию вручную через базу.")
    buttons = [[InlineKeyboardButton(text=row["category"].capitalize(), callback_data=f"cat_{row['category']}")]
               for row in rows]
    # Добавляем кнопку для ввода новой категории
    buttons.append([InlineKeyboardButton(text="🆕 Добавить новую", callback_data="add_new_category")])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await state.set_state(AddProduct.category)
    await message.answer("📂 Выберите категорию или добавьте новую:", reply_markup=markup)

@dp.callback_query(lambda c: c.data.startswith("cat_"))
async def step_category(callback: types.CallbackQuery, state: FSMContext):
    category = callback.data.replace("cat_", "")
    await state.update_data(category=category)
    await callback.message.edit_reply_markup()
    await state.set_state(AddProduct.price)
    await callback.message.answer("💰 Введите *цену* товара (только число):", parse_mode="Markdown")

@dp.callback_query(F.data == "add_new_category")
async def add_new_category(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddProduct.category)
    await callback.message.answer("Введите название новой категории:")

@dp.message(AddProduct.category)
async def new_category_input(message: types.Message, state: FSMContext):
    new_category = message.text.strip().lower()
    await state.update_data(category=new_category)
    await state.set_state(AddProduct.price)
    await message.answer("💰 Введите *цену* товара (только число):", parse_mode="Markdown")

@dp.message(AddProduct.price)
async def step_price(message: types.Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❌ Введите только число без символов.")
    await state.update_data(price=message.text.strip())
    await state.set_state(AddProduct.contact)
    await message.answer("📱 Введите контакт или @юзернейм для связи:")

@dp.message(AddProduct.contact)
async def step_contact(message: types.Message, state: FSMContext):
    await state.update_data(contact=message.text.strip())
    # Переходим к шагу загрузки фотографии
    await state.set_state(AddProduct.photo)
    await message.answer("📸 Пришлите фотографию товара:")

@dp.message(AddProduct.photo, F.photo)
async def step_photo(message: types.Message, state: FSMContext):
    photo_file_id = message.photo[-1].file_id
    await state.update_data(photo=photo_file_id)
    data = await state.get_data()
    user_id = message.from_user.id
    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO products (user_id, name, category, price, contacts, photo)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            user_id, data["name"], data["category"], data["price"], data["contact"], data["photo"]
        )
    contact_btn = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📞 Связаться", url=f"https://t.me/{data['contact'].strip().lstrip('@')}")]]
    )
    product_message = (
        f"✅ Объявление добавлено!\n\n"
        f"*{data['name']}* — {data['price']} ₽\n"
        f"Категория: {data['category'].capitalize()}"
    )
    # Отправляем объявление пользователю (в чате бота)
    await message.answer_photo(
        photo=data["photo"],
        caption=product_message,
        parse_mode="Markdown",
        reply_markup=contact_btn
    )
    await state.clear()

# --- Просмотр объявлений ---
@dp.message(F.text == "📜 Все товары")
async def all_items(message: types.Message):
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT name, price, contacts, photo FROM products ORDER BY created_at DESC LIMIT 5")
    if not rows:
        return await message.answer("Нет объявлений.")
    for row in rows:
        caption = f"{row['name']} – {row['price']} ₽\nКонтакт: {row['contacts']}"
        await message.answer_photo(photo=row['photo'], caption=caption)

@dp.message(F.text == "🔍 Найти")
async def find_menu(message: types.Message):
    buttons = [
        [InlineKeyboardButton(text="🔤 По названию", callback_data="search_name")],
        [InlineKeyboardButton(text="📂 По категории", callback_data="search_category")]
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Как хотите искать товар?", reply_markup=markup)

@dp.callback_query(F.data == "search_name")
async def search_by_name_prompt(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SearchState.by_name)
    await callback.message.answer("🔤 Введите название товара:")

@dp.message(SearchState.by_name)
async def search_by_name_result(message: types.Message, state: FSMContext):
    keyword = message.text.strip().lower()
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT name, price, contacts, photo FROM products WHERE LOWER(name) LIKE $1 ORDER BY created_at DESC LIMIT 5",
            f"%{keyword}%"
        )
    await state.clear()
    if not rows:
        return await message.answer("❌ Ничего не найдено.")
    for row in rows:
        caption = f"{row['name']} – {row['price']} ₽\nКонтакт: {row['contacts']}"
        await message.answer_photo(photo=row['photo'], caption=caption)

@dp.callback_query(F.data == "search_category")
async def search_by_category(callback: types.CallbackQuery):
    pool = await get_db()
    async with pool.acquire() as conn:
        categories = await conn.fetch("SELECT DISTINCT category FROM products ORDER BY category")
    if not categories:
        return await callback.message.answer("❌ Категорий пока нет.")
    buttons = [
        [InlineKeyboardButton(text=cat['category'].capitalize(), callback_data=f"search_cat_{cat['category']}")]
        for cat in categories
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("📂 Выберите категорию:", reply_markup=markup)

@dp.callback_query(lambda c: c.data.startswith("search_cat_"))
async def search_category_result(callback: types.CallbackQuery):
    category = callback.data.replace("search_cat_", "")
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT name, price, contacts, photo FROM products WHERE category = $1 ORDER BY created_at DESC LIMIT 5",
            category
        )
    if not rows:
        return await callback.message.answer(f"❌ Нет товаров в категории {category}")
    for row in rows:
        caption = f"{row['name']} – {row['price']} ₽\nКонтакт: {row['contacts']}"
        await callback.message.answer_photo(photo=row['photo'], caption=caption)

@dp.message(F.text == "🧾 Мои объявления")
async def my_products(message: types.Message):
    user_id = message.from_user.id
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name, price FROM products WHERE user_id = $1 ORDER BY created_at DESC", user_id)
    if not rows:
        return await message.answer("У вас нет объявлений.")
    result = "🧾 Ваши объявления:\n\n"
    for row in rows:
        result += f"🆔 {row['id']}: {row['name']} – {row['price']} ₽\n"
        result += f"✏️ /edit_{row['id']}    ❌ /delete_{row['id']}\n\n"
    await message.answer(result)

# --- Редактирование объявления ---
@dp.message(F.text.startswith("/edit_"))
async def edit_product(message: types.Message, state: FSMContext):
    try:
        product_id = int(message.text.split("_")[1])
    except (IndexError, ValueError):
        return await message.answer("Неверный ID объявления.")
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM products WHERE id = $1", product_id)
    if not row:
        return await message.answer("Объявление не найдено.")
    if row['user_id'] != message.from_user.id:
        return await message.answer("Вы не можете редактировать чужие объявления.")
    await state.update_data(product_id=product_id)
    buttons = [
        [InlineKeyboardButton(text="✏️ Название", callback_data="edit_field_name")],
        [InlineKeyboardButton(text="📂 Категория", callback_data="edit_field_category")],
        [InlineKeyboardButton(text="💰 Цена", callback_data="edit_field_price")],
        [InlineKeyboardButton(text="📱 Контакт", callback_data="edit_field_contact")],
        [InlineKeyboardButton(text="✅ Завершить", callback_data="edit_finish")]
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await state.set_state(EditProduct.choosing_field)
    await message.answer("Выберите, что хотите изменить:", reply_markup=markup)

@dp.callback_query(lambda c: c.data.startswith("edit_field_") and c.data != "edit_field_category")
async def edit_field_handler(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.replace("edit_field_", "")
    await state.update_data(field=field)
    await callback.message.answer(f"Введите новое значение для {field}:")
    await state.set_state(EditProduct.waiting_for_input)

@dp.callback_query(F.data == "edit_field_category")
async def edit_field_category(callback: types.CallbackQuery, state: FSMContext):
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT category FROM products ORDER BY category")
    if not rows:
        return await callback.message.answer("Нет категорий в базе.")
    buttons = [[InlineKeyboardButton(text=row["category"].capitalize(), callback_data=f"edit_cat_{row['category']}")]
               for row in rows]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("Выберите новую категорию:", reply_markup=markup)

@dp.callback_query(lambda c: c.data.startswith("edit_cat_"))
async def edit_category_selection(callback: types.CallbackQuery, state: FSMContext):
    new_category = callback.data.replace("edit_cat_", "")
    data = await state.get_data()
    product_id = data.get("product_id")
    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE products SET category = $1 WHERE id = $2", new_category, product_id)
    await callback.message.answer(f"Категория обновлена на {new_category.capitalize()}.")
    buttons = [
        [InlineKeyboardButton(text="✏️ Название", callback_data="edit_field_name")],
        [InlineKeyboardButton(text="📂 Категория", callback_data="edit_field_category")],
        [InlineKeyboardButton(text="💰 Цена", callback_data="edit_field_price")],
        [InlineKeyboardButton(text="📱 Контакт", callback_data="edit_field_contact")],
        [InlineKeyboardButton(text="✅ Завершить", callback_data="edit_finish")]
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("Выберите, что хотите изменить:", reply_markup=markup)
    await state.set_state(EditProduct.choosing_field)

@dp.message(EditProduct.waiting_for_input)
async def process_edit_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("field")
    product_id = data.get("product_id")
    new_value = message.text.strip()
    if field == "price" and not new_value.isdigit():
        return await message.answer("Цена должна быть числом.")
    pool = await get_db()
    query = f"UPDATE products SET {field} = $1 WHERE id = $2"
    async with pool.acquire() as conn:
        await conn.execute(query, new_value, product_id)
    await message.answer(f"{field.capitalize()} обновлено.")
    buttons = [
        [InlineKeyboardButton(text="✏️ Название", callback_data="edit_field_name")],
        [InlineKeyboardButton(text="📂 Категория", callback_data="edit_field_category")],
        [InlineKeyboardButton(text="💰 Цена", callback_data="edit_field_price")],
        [InlineKeyboardButton(text="📱 Контакт", callback_data="edit_field_contact")],
        [InlineKeyboardButton(text="✅ Завершить", callback_data="edit_finish")]
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Выберите, что хотите изменить:", reply_markup=markup)
    await state.set_state(EditProduct.choosing_field)

@dp.callback_query(F.data == "edit_finish")
async def finish_edit(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Редактирование завершено.")

# --- Удаление объявления ---
@dp.message(F.text.startswith("/delete_"))
async def delete_product(message: types.Message, state: FSMContext):
    try:
        product_id = int(message.text.split("_")[1])
    except (IndexError, ValueError):
        return await message.answer("Неверный ID объявления.")
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM products WHERE id = $1", product_id)
    if not row:
        return await message.answer("Объявление не найдено.")
    if row['user_id'] != message.from_user.id:
        return await message.answer("Вы не можете удалять чужие объявления.")
    buttons = [
        [InlineKeyboardButton(text="✅ Да", callback_data=f"delete_confirm_{product_id}"),
         InlineKeyboardButton(text="❌ Нет", callback_data=f"delete_cancel_{product_id}")]
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Вы уверены, что хотите удалить объявление?", reply_markup=markup)

@dp.callback_query(lambda c: c.data.startswith("delete_confirm_"))
async def confirm_delete(callback: types.CallbackQuery, state: FSMContext):
    try:
        product_id = int(callback.data.split("_")[-1])
    except (IndexError, ValueError):
        return await callback.message.answer("Неверный ID объявления.")
    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM products WHERE id = $1", product_id)
    await callback.message.answer("Объявление удалено.")

@dp.callback_query(lambda c: c.data.startswith("delete_cancel_"))
async def cancel_delete(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Удаление отменено.")

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
