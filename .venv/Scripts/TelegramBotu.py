import yfinance as yf
import logging
from textblob import TextBlob
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import requests
from binance.client import Client
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, JobQueue, MessageHandler, filters
from dotenv import load_dotenv
import os
import matplotlib.pyplot as plt
import numpy as np
from telegram import InputFile
import datetime
from binance.client import Client
from telegram import BotCommand

# Çevresel değişkenlerin yüklenmesi
load_dotenv()

API_KEY = os.getenv('API_KEY')
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
TOKEN = os.getenv('TOKEN')

# Logging yapılandırması
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Binance Client
client = Client(api_key=BINANCE_API_KEY, requests_params={'timeout': 30})


async def set_bot_commands(application: Application):
    commands = [
        BotCommand('start', 'Botu başlatır ve hoş geldiniz mesajı gönderir'),
        BotCommand('help', 'Yardım mesajını gösterir'),
        BotCommand('stock', 'Bir sembolün fiyatını gösterir (örnek: /stock BTCUSDT)'),
        BotCommand('news', 'Anahtar kelimeyle ilgili borsa haberlerini getirir (örnek: /news Bitcoin)'),
        BotCommand('symbols', 'Desteklenen döviz ve kripto sembollerini listeler'),
        BotCommand('set_alert', 'Bir sembol için fiyat bildirimi ayarlar (örnek: /set_alert BTCUSDT 50000)'),
        BotCommand('plot_stock', 'Bir sembolün fiyat hareket grafiğini gönderir (örnek: /plot_stock BTCUSDT)'),
        BotCommand('convert_currency', 'Döviz veya kripto para dönüşümü yapar (örnek: /convert_currency 40 USDTRY)')
    ]

    await application.bot.set_my_commands(commands)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_type: str = update.message.chat.type
    text: str = update.message.text

    print(f'User ({update.message.chat.id}) in {message_type}: "{text}"')

    if message_type == 'group':
        if BOT_USERNAME in text:
            new_text: str = text.replace(BOT_USERNAME, '').strip()
            response: str = handle_response(new_text)
        else:
            return
    else:
        response: str = handle_response(text)

    print('Bot:', response)
    await update.message.reply_text(response)

# Telegram bot komutları ve işlemleri
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('👋 Merhaba! Ben borsa takip botuyum. Komutları görmek için /help kullanabilirsiniz.')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📜 Borsa Takip Botu Komutları:\n\n"
        "/start - Botu başlatır ve hoş geldiniz mesajı gönderir.\n"
        "/help - Bu yardım mesajını gösterir.\n\n"

        "📈 Fiyat ve Kripto Para Bilgisi:\n"
        "/stock <sembol> - Kripto para ya da döviz fiyatını gösterir. Örnek: /stock BTCUSDT (Bitcoin), /stock USDTRY (Dolar/TL)\n"
        "/symbols - Desteklenen kripto para ve döviz sembollerini listeler.\n\n"

        "💹 Haber ve Analiz:\n"
        "/news <anahtar kelime> - Belirtilen anahtar kelimeyle ilgili borsa haberlerini getirir. Seçebileceğiniz anahtar kelimeler:"
        "borsa, hisse, piyasa, yatırım, kripto\n"

        "⏰ Bildirimler:\n"
        "/set_alert <sembol> <fiyat> - Belirtilen sembol için fiyat bildirim ayarlar. Örnek: /set_alert BTCUSDT 50000\n\n"

        "📊 Grafik Görüntüleme:\n"
        "/plot_stock <sembol> - Belirtilen sembolün fiyat hareketi grafiğini gönderir. Örnek: /plot_stock BTCUSDT\n\n"

        "💱 Dönüşüm Bilgisi:\n"
        "/convert_currency <miktar> <sembol> - Belirtilen miktar ve sembol için döviz veya kripto para dönüşümünü yapar. Örnek: /convert_currency 40 USDTRY, /convert_currency 1 BTCUSDT\n"
    )
    await update.message.reply_text(help_text)


# Kullanıcı bildirimlerini saklamak için bir sözlük
user_alerts = {}

# Kullanıcıdan koşul alma komutu
async def set_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) != 2:
            await update.message.reply_text("⚠ Lütfen doğru formatta girin: /set_alert <sembol> <fiyat>")
            return

        symbol = context.args[0].upper()
        target_price = float(context.args[1])

        user_id = update.message.from_user.id
        user_alerts[user_id] = (symbol, target_price)

        await update.message.reply_text(f"✅ {symbol} için {target_price} fiyatında bir bildirim ayarlandı.")
    except ValueError:
        await update.message.reply_text("⚠ Lütfen geçerli bir fiyat girin.")


# Fiyat kontrolü ve bildirim gönderme
async def check_alerts(context):
    for user_id, (symbol, target_price) in user_alerts.items():
        try:
            # Fiyatı al
            ticker = yf.Ticker(symbol + "=X").history(period="1d")
            current_price = ticker['Close'].iloc[-1]

            # Fiyat hedefini kontrol et
            if current_price >= target_price:
                await context.bot.send_message(chat_id=user_id, text=f"📈 {symbol} fiyatı {current_price:.2f} TL'ye ulaştı!")
                # Bildirimi gönderdikten sonra kullanıcıyı listeden kaldır
                del user_alerts[user_id]
        except Exception as e:
            logger.error(f"Fiyat kontrol hatası: {e}")


# Haberleri çekme ve filtreleme fonksiyonu
def fetch_news(keyword, page=1, page_size=10):
    base_url = 'https://newsapi.org/v2/everything'
    related_keywords = ["borsa", "hisse", "piyasa", "yatırım", "kripto"]
    query = f"{keyword} AND ({' OR '.join(related_keywords)})"
    params = {
        'q': query,
        'apiKey': API_KEY,
        'language': 'tr',
        'sortBy': 'publishedAt',
        'page': page,
        'pageSize': page_size,
    }
    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        news_data = response.json()
        if news_data.get('totalResults', 0) > 0:
            filtered_articles = [
                article for article in news_data['articles']
                if any(kw in (article['title'] + article.get('description', '')) for kw in related_keywords)
            ]
            return filtered_articles
        else:
            return []
    except requests.exceptions.RequestException as e:
        logger.error(f"API Hatası: {e}")
        return []

async def get_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) == 0:
            await update.message.reply_text("⚠ Lütfen bir sembol girin! Örneğin: /stock BTCUSDT veya /stock USDTRY")
            return

        symbol = context.args[0].upper()

        # Döviz kuru sembolü için =X ekleyelim
        symbol_for_api = symbol
        if symbol.endswith("TRY"):
            symbol_for_api = symbol + "=X"  # USDTRY gibi semboller için '=X' eklenmeli

        # Kripto para sembollerine göre işlem yapma (örneğin BTCUSDT)
        if symbol.endswith("USDT") or symbol.endswith("BTC"):
            ticker = client.get_symbol_ticker(symbol=symbol)
            price = float(ticker['price'])
            await update.message.reply_text(f"💰 {symbol} güncel fiyatı: {price:.2f} USD")
        else:
            # Döviz kurları için Yahoo Finance kullan
            forex_data = yf.Ticker(symbol_for_api)  # USDTRY=X gibi döviz sembollerini kullanıyoruz
            data = forex_data.history(period="1d")

            if data.empty:
                await update.message.reply_text(f"⚠ {symbol} için veri alınamadı. Lütfen sembolü kontrol edin.")
            else:
                forex_price = data['Close'].iloc[-1]  # En son kapanış fiyatı
                # Yalnızca sembolün esas kısmını göster
                symbol_display = symbol.replace("=X", "")
                await update.message.reply_text(f"💸 {symbol_display} güncel fiyatı: {forex_price:.2f} {symbol_display[-3:]}")

        # Grafik gönder
        await plot_stock(symbol_for_api, update)  # Burada await kullanıyoruz

    except Exception as e:
        logger.error(f"Fiyat Alma Hatası: {e}")
        await update.message.reply_text(f"❌ Bir hata oluştu. Lütfen geçerli bir sembol girin. Hata: {e}")


async def fetch_keyword_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) == 0:
            await update.message.reply_text("⚠ Lütfen bir anahtar kelime girin! Örneğin: /news Bitcoin")
            return
        keyword = " ".join(context.args)
        news_articles = fetch_news(keyword)
        if news_articles:
            message = f"📰 {keyword} ile ilgili borsa haberleri:\n"
            for idx, article in enumerate(news_articles[:5], 1):
                message += f"\n{idx}. {article['title']}\n🔗 Link: {article['url']}\n"
            await update.message.reply_text(message)
        else:
            await update.message.reply_text("🚫 Bu anahtar kelime ile ilgili borsa haberi bulunamadı.")

    except Exception as e:
        logger.error(f"Haber Getirme Hatası: {e}")
        await update.message.reply_text("❌ Bir hata oluştu.")

async def get_supported_stocks_dynamic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Kripto sembollerinin listesi
        important_crypto_symbols = [
            "BTCUSDT", "ETHUSDT", "XRPUSDT", "LTCUSDT", "BCHUSDT", "DOGEUSDT", "ADAUSDT", "SOLUSDT"
        ]

        # Kripto sembollerini mesaj olarak oluştur
        crypto_message = "💎 Desteklenen Kripto Semboller:\n"
        crypto_message += "\n".join([f"• {symbol}" for symbol in important_crypto_symbols])

        # Döviz sembollerini tanımla
        forex_symbols = {
            'USD': 'Amerikan Doları (USD)',
            'EUR': 'Euro (EUR)',
            'GBP': 'İngiliz Sterlini (GBP)',
            'JPY': 'Japon Yeni (JPY)',
            'CHF': 'İsviçre Frangı (CHF)',
            'AUD': 'Avustralya Doları (AUD)',
            'CAD': 'Kanada Doları (CAD)',
            'BTC': 'Bitcoin (BTC)',
            'ETH': 'Ethereum (ETH)',
            'NZD': 'Yeni Zelanda Doları (NZD)'
        }

        # Döviz sembollerinin fiyatlarını al
        forex_symbols_display = []
        for base, description in forex_symbols.items():
            try:
                forex_data = yf.Ticker(f"{base}TRY=X")  # Örneğin USDTRY=X sembolü
                forex_price = forex_data.history(period="1d")['Close'].iloc[-1]
                forex_symbols_display.append(f"• {base} - {description}")
            except Exception as e:
                logger.error(f"Döviz Verisi Alma Hatası: {e} {base}")

        # Döviz sembollerinin mesajını oluştur
        forex_message = "\n\n*💰 Döviz Semboller (TRY cinsinden):*\n" + "\n".join(forex_symbols_display)

        # Birleştirilmiş mesaj
        final_message = f"{crypto_message}\n{forex_message}\n\n🔗 Daha fazla kripto verisi için [Binance](https://www.binance.com) sitesini ziyaret edebilirsiniz."

        # Mesajı göndermek
        await update.message.reply_text(final_message, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Desteklenen Semboller Hatası: {e}")
        await update.message.reply_text("❌ Sembol listesi alınırken bir hata oluştu.")

async def convert_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Kullanıcının girdiği sembol (örn. BTCUSDT, EURUSD)
        if len(context.args) < 2:
            await update.message.reply_text("⚠ Lütfen doğru formatta girin: /convert_currency <miktar> <sembol> (örn. /convert_currency 40 USDTRY)")
            return

        amount = float(context.args[0])  # Kullanıcının girdiği miktar
        symbol = context.args[1].upper()  # Kullanıcının girdiği sembolü alıyoruz

        # Eğer sembol bir kripto para ise (USDT, BTC gibi)
        if symbol.endswith("USDT") or symbol.endswith("BTC"):
            ticker = Client(api_key=BINANCE_API_KEY).get_symbol_ticker(symbol=symbol)
            conversion_rate = float(ticker['price'])
            converted_amount = amount * conversion_rate
            await update.message.reply_text(f"💰 {amount} {symbol} = {converted_amount:.2f} USDT")
        else:
            # Döviz kuru sembolü için (EURTRY, USDTRY gibi)
            ticker = yf.Ticker(f"{symbol}=X")
            data = ticker.history(period="1d")
            conversion_rate = data['Close'].iloc[-1]  # Son kapanış fiyatı
            converted_amount = amount * conversion_rate
            await update.message.reply_text(f"💰 {amount} {symbol} = {converted_amount:.2f} TRY")

    except Exception as e:
        logger.error(f"Döviz/Kripto dönüşüm hatası: {e}")
        await update.message.reply_text("❌ Döviz veya kripto para kurlarını alırken bir hata oluştu.")

async def plot_stock(symbol, update):
    try:
        # Eğer sembol kripto para ise Binance API'si ile veri alalım
        if symbol.endswith("USDT") or symbol.endswith("BTC"):
            # Binance üzerinden son 5 günün verisini alıyoruz
            klines = client.get_historical_klines(symbol, Client.KLINE_INTERVAL_1DAY, "5 days ago UTC")
            dates = [kline[0] for kline in klines]
            prices = [float(kline[4]) for kline in klines]  # Kapanış fiyatları

            # Tarihleri formatla
            dates = [datetime.datetime.utcfromtimestamp(date / 1000).strftime('%Y-%m-%d') for date in dates]

        else:
            # Eğer sembol döviz kuru ise Yahoo Finance API'si ile veri alalım
            data = yf.Ticker(symbol).history(period="5d")
            if data.empty:
                await update.message.reply_text(f"⚠ {symbol} için veri alınamadı. Lütfen sembolü kontrol edin.")
                return

            dates = data.index.strftime('%Y-%m-%d')
            prices = data['Close']

        # Grafik oluşturma
        plt.figure(figsize=(10, 6))
        plt.plot(dates, prices, marker='o', linestyle='-', color='blue', label='Fiyat')
        plt.title(f'{symbol} Fiyat Hareketi (Son 5 Gün)', fontsize=14)  # Başlıkta period güncellendi
        plt.xlabel('Tarih', fontsize=12)
        plt.ylabel('Fiyat', fontsize=12)
        plt.xticks(rotation=45, fontsize=10)
        plt.legend()
        plt.grid(alpha=0.3)
        plt.tight_layout()

        # Grafiği kaydet
        file_path = 'stock_chart.png'
        plt.savefig(file_path)
        plt.close()

        # Grafiği Telegram'a gönder
        with open(file_path, 'rb') as chart_file:
            await update.message.reply_photo(photo=InputFile(chart_file, filename="stock_chart.png"))

    except ValueError as ve:
        logger.error(f"Değer hatası: {ve}")
        await update.message.reply_text("⚠ Geçersiz sembol veya dönem.")
    except Exception as e:
        logger.error(f"Grafik oluşturma hatası: {e}")
        await update.message.reply_text(f"❌ Grafik oluşturulurken bir hata oluştu. Hata: {e}")

async def plot_stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) == 0:
            await update.message.reply_text("⚠ Lütfen bir sembol girin! Örneğin: /plot_stock BTCUSDT")
            return

        symbol = context.args[0].upper()

        # Stock grafiğini oluştur
        await plot_stock(symbol, update)

    except Exception as e:
        logger.error(f"Grafik Gönderme Hatası: {e}")
        await update.message.reply_text("❌ Bir hata oluştu.")

# Telegram bot ana fonksiyonu
if __name__ == "__main__":
    print("Bot başlıyor... 🎉")
    app = Application.builder().token(TOKEN).build()

    # Komutlar
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('stock', get_stock))
    app.add_handler(CommandHandler('news', fetch_keyword_news))
    app.add_handler(CommandHandler('symbols', get_supported_stocks_dynamic))
    app.add_handler(CommandHandler('set_alert', set_alert))
    app.add_handler(CommandHandler('plot_stock', plot_stock_command))
    app.add_handler(CommandHandler('convert_currency', convert_currency))  # Yeni komut ekledik

    # JobQueue ile arka planda fiyat kontrolü yapma
    job_queue = app.job_queue
    job_queue.run_repeating(check_alerts, interval=300, first=0)  # Her 5 dakikada bir kontrol et

    # Bot komutlarını ayarla
    #app.initialize()
    #app.loop.run_until_complete(set_bot_commands(app))

    # Mesaj işleyici
    app.add_handler(MessageHandler(filters.TEXT, handle_message))

    # Hata işleme
    app.add_error_handler(lambda update, context: logger.error(f"Update {update} caused error {context.error}"))

    print("Bot çalışıyor... 🟢")
    import asyncio
    app.run_polling(poll_interval=3, timeout=20)