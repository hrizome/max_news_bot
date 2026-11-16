import os
import time
import random
import requests
import urllib3
import feedparser
import re
from bs4 import BeautifulSoup
from google import genai

os.environ['NO_PROXY'] = '*'
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Ключи берутся из Secrets GitHub
MAX_BOT_TOKEN = os.environ.get("f9LHodD0cOIshsPFhJY9QS97BIti5pqfuxsCH04w3NFo5w8ZvZeAE0ZpXmReJZ5GBGw3rdKtygkGrXI7hFHY")
MAX_CHAT_ID = os.environ.get("-72654091307543")
GEMINI_API_KEY = os.environ.get("AQ.Ab8RN6L20Jj9A87Sf_5KM9DTMuW1CEaCafDJcR4Zl1Qq1LDtsA")

RSS_URL = "https://ria.ru/export/rss2/archive/index.xml"
HISTORY_FILE = "sent_news.txt"

client = genai.Client(api_key=GEMINI_API_KEY)

def load_sent_news():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f)

def save_sent_news(link):
    with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{link}\n")

def get_ai_summary(link):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(link, headers=headers, verify=False, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        summary_header = soup.find(string=re.compile('Краткий пересказ'))
        if summary_header:
            parent = summary_header.find_parent()
            if parent:
                list_block = parent.find_next(['ul', 'ol'])
                if list_block:
                    items = list_block.find_all('li')
                    if items:
                        text_parts = [item.get_text(strip=True) for item in items]
                        return "\n".join([f"• {part}" for part in text_parts])
        return None
    except Exception as e:
        print(f"Ошибка при парсинге страницы: {e}")
        return None

def get_best_news():
    print("Читаю RSS-ленту...")
    feed = feedparser.parse(RSS_URL)
    
    if not feed.entries:
        print("❌ Не удалось получить новости.")
        return None

    sent_links = load_sent_news()
    new_entries = [entry for entry in feed.entries if entry.link not in sent_links]
    
    if not new_entries:
        print("🤷‍♂️ Новых новостей нет.")
        return None

    entries_to_analyze = new_entries[:10]
    print("Проверяю наличие текста у новостей...")
    valid_entries = []
    
    for entry in entries_to_analyze:
        summary = get_ai_summary(entry.link)
        
        if not summary:
            description = entry.get('summary', '') or entry.get('description', '')
            cleanr = re.compile('<.*?>')
            summary = re.sub(cleanr, '', description).strip()
            
        if summary and len(summary) > 10:
            entry.custom_summary = summary
            valid_entries.append(entry)
        else:
            print(f"⏩ Пропускаю новость без текста: {entry.title}")

    if not valid_entries:
        print("🤷‍♂️ Нет новостей с нормальным текстом.")
        return None

    titles_list = "\n".join([f"{i+1}. {entry.title}" for i, entry in enumerate(valid_entries)])
    print(f"Отправляю {len(valid_entries)} заголовков в Gemini...")
    
    prompt = f"""
    Ты — главный редактор новостного канала для простых людей в России.
    Твоя задача: выбрать из списка ОДНУ самую важную новость.
    
    Приоритеты (по убыванию важности):
    1. Для простых людей: здоровье, цены, ЖКХ, пенсии, зарплаты, льготы, налоги, бензин.
    2. Глобальное: политика РФ (Путин, Кремль, Госдума), безопасность, крупные ЧП.
    
    Игнорируй: спорт, развлечения, новости про США (если они не влияют напрямую на Россию).
    
    Вот список заголовков:
    {titles_list}
    
    Верни ТОЛЬКО номер самой важной новости (одно число, например: 3).
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-3.8-flash', 
            contents=prompt
        )
        
        answer = response.text.strip()
        print(f"Ответ Gemini: {answer}")
        
        match = re.search(r'\d+', answer)
        if match:
            best_index = int(match.group()) - 1
            if 0 <= best_index < len(valid_entries):
                best_entry = valid_entries[best_index]
            else:
                best_entry = valid_entries[0]
        else:
            best_entry = valid_entries[0]
            
    except Exception as e:
        print(f"⚠️ Ошибка Gemini: {e}. Использую первую новость из валидных.")
        best_entry = valid_entries[0]

    title = best_entry.title
    link = best_entry.link
    ai_summary = best_entry.custom_summary
    
    print(f"🏆 Выбрана новость: {title}")
    
    emoji = "📰"
    if "БПЛА" in title or "атака" in title:
        emoji = "🚨"
    elif "Минздрав" in title or "грипп" in title or "врач" in title:
        emoji = "🩺"
    elif "экономик" in title.lower() or "рубл" in title or "цена" in title:
        emoji = "📈"

    post_text = f"{emoji} **{title}**\n\n"
    post_text += f"{ai_summary}\n\n"
    post_text += f"[Подробнее]({link})"

    return post_text, link

def publish_to_max(text):
    url = f"https://platform-api2.max.ru/messages?chat_id={MAX_CHAT_ID}"
    headers = {
        "Authorization": MAX_BOT_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "format": "markdown",      
        "disable_link_preview": True 
    }
    
    print("Отправляю запрос в MAX...")
    response = requests.post(url, headers=headers, json=payload, verify=False, timeout=15)
    
    if response.status_code == 200:
        print("✅ Пост успешно опубликован!")
        return True
    else:
        print(f"❌ Ошибка {response.status_code}: {response.text}")
        return False

if __name__ == "__main__":
    # Случайная задержка от 0 до 240 секунд (4 минуты)
    # Ограничено 4 минутами, чтобы GitHub Actions не убил процесс по таймауту
    delay = random.randint(0, 240) 
    print(f"⏳ Пауза {delay} секунд (имитация живого редактора)...")
    time.sleep(delay)
    
    result = get_best_news()
    if result:
        news_text, news_link = result
        if publish_to_max(news_text):
            save_sent_news(news_link)
            print("История обновлена. Ссылка сохранена.")
