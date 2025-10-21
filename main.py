import discord
import json
import re
import asyncio
import time
from datetime import datetime, time as dt_time
from typing import Dict, List, Optional, Tuple

class AmazonMonitorBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        
        # 設定を読み込み
        with open('config.json', 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        self.monitor_channel_id = int(self.config['monitor_channel_id'])
        self.post_channel_id = int(self.config['post_channel_id'])
        self.is_connected = False
        self.retry_count = 0
        self.max_retries = 5
        self.notification_times = [dt_time(7, 0), dt_time(12, 0), dt_time(15, 0), dt_time(18, 0), dt_time(21, 0)]
        self.last_notification_date = None
    
    async def on_ready(self):
        print("Bot起動完了")
        print(f'{self.user} としてログインしました')
        print(f'監視チャンネルID: {self.monitor_channel_id}')
        print(f'投稿先チャンネルID: {self.post_channel_id}')
        
        # 起動通知を投稿
        await self.send_startup_notification()
        
        self.is_connected = True
        self.retry_count = 0
        
        # 定期通知タスクを開始
        asyncio.create_task(self.periodic_notification_task())
    
    async def send_startup_notification(self):
        """起動通知を投稿"""
        try:
            # まずget_channelで試行
            post_channel = self.get_channel(self.post_channel_id)
            print(f"投稿チャンネル取得試行 (get_channel): {self.post_channel_id}")
            
            # get_channelで取得できない場合、fetch_channelを使用
            if not post_channel:
                print("get_channelで取得失敗。fetch_channelで再試行...")
                try:
                    post_channel = await self.fetch_channel(self.post_channel_id)
                    print(f"fetch_channelで取得成功: {post_channel.name}")
                except discord.NotFound:
                    print(f"エラー: チャンネルID {self.post_channel_id} が見つかりません")
                except discord.Forbidden:
                    print(f"エラー: チャンネルID {self.post_channel_id} へのアクセス権限がありません")
                except Exception as e:
                    print(f"fetch_channel エラー: {e}")
            else:
                print(f"投稿チャンネル取得成功: {post_channel.name} (サーバー: {post_channel.guild.name})")
            
            if post_channel:
                current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                embed = discord.Embed(
                    title="🤖 Amazon監視BOT起動",
                    description=f"監視を開始しました\n起動時刻: {current_time}",
                    color=0x00ff00
                )
                embed.add_field(
                    name="監視チャンネル", 
                    value=f"<#{self.monitor_channel_id}>", 
                    inline=True
                )
                embed.add_field(
                    name="投稿チャンネル", 
                    value=f"<#{self.post_channel_id}>", 
                    inline=True
                )
                await post_channel.send(embed=embed)
                print("起動通知を投稿しました")
            else:
                print(f"投稿チャンネルが見つかりません: {self.post_channel_id}")
                print("ボットが参加しているサーバーとチャンネル:")
                for guild in self.guilds:
                    print(f"  サーバー: {guild.name} (ID: {guild.id})")
                    for channel in guild.text_channels:
                        print(f"    - {channel.name} (ID: {channel.id})")
        except Exception as e:
            print(f"起動通知エラー: {e}")
            import traceback
            traceback.print_exc()
    
    async def on_disconnect(self):
        """接続切断時の処理"""
        print("接続が切断されました")
        self.is_connected = False
    
    async def on_error(self, event, *args, **kwargs):
        """エラー発生時の処理"""
        import traceback
        print(f"エラーが発生しました: {event}")
        traceback.print_exc()
    
    async def on_resumed(self):
        """再接続時の処理"""
        print("接続が復旧しました")
        self.is_connected = True
        # 再接続通知を投稿（無効化）
        # await self.send_reconnect_notification()
    
    async def send_reconnect_notification(self):
        """再接続通知を投稿"""
        try:
            post_channel = self.get_channel(self.post_channel_id)
            if not post_channel:
                try:
                    post_channel = await self.fetch_channel(self.post_channel_id)
                except Exception as e:
                    print(f"復旧通知: チャンネル取得失敗 ({e})")
                    return
            
            if post_channel:
                current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                embed = discord.Embed(
                    title="🔄 Amazon監視BOT復旧",
                    description=f"接続が復旧しました\n復旧時刻: {current_time}",
                    color=0xffff00
                )
                await post_channel.send(embed=embed)
                print("復旧通知を投稿しました")
        except Exception as e:
            print(f"復旧通知エラー: {e}")
    
    async def on_message(self, message):
        # BOT自身のメッセージは無視
        if message.author == self.user:
            return
        
        # 監視チャンネル以外は無視
        if message.channel.id != self.monitor_channel_id:
            return
        
        # 接続状態チェック
        if not self.is_connected:
            print("接続が切断されています。メッセージをスキップします。")
            return
        
        print(f"メッセージ検知: {message.id}")
        
        # デバッグ用：メッセージ内容を表示
        print(f"メッセージ内容（最初の200文字）: {message.content[:200]}...")
        
        try:
            # メッセージ解析
            parsed_data = self.parse_message(message.content)
            if not parsed_data:
                print("解析失敗: スキップ")
                return
            
            print(f"解析成功: {parsed_data['product_name']}")
            
            # 利益判定
            if self.check_profit(parsed_data):
                print("利益判定: 投稿対象")
                await self.post_message(parsed_data)
            else:
                print("利益判定: スキップ")
                
        except Exception as e:
            print(f"メッセージ処理エラー: {e}")
            await self.handle_error("メッセージ処理", e)
    
    def parse_message(self, content: str) -> Optional[Dict]:
        """メッセージを解析して商品情報を抽出"""
        try:
            # 基本的な構造チェック
            if "🛒 Amazon" not in content or "・" not in content:
                print("構造チェック失敗: 🛒 Amazon または ・ が見つかりません")
                return None
            
            # 商品名抽出（購入可能数以外の最初の・を探す）
            # 購入可能数のパターンを除外して商品名を抽出
            lines = content.split('\n')
            product_name = None
            for line in lines:
                if line.strip().startswith('・') and '個まで購入可能🛒' not in line:
                    product_name = line.strip()[1:].strip()  # ・を除去
                    break
            
            if not product_name:
                print("商品名抽出失敗")
                return None
            
            # JANコード抽出
            jan_match = re.search(r'・JAN：(\d+)', content)
            if not jan_match:
                print("JANコード抽出失敗")
                return None
            jan_code = jan_match.group(1)
            
            # 購入可能数抽出
            purchase_match = re.search(r'・(\d+)個まで購入可能🛒', content)
            purchase_count = purchase_match.group(1) if purchase_match else None
            
            # Amazon価格抽出（🉐の行から）
            # パターン1: 🉐 171（AMEX）：2.5%\n　   97（Amazon）：1.4%
            # パターン2: 🉐 1000（Amazon・AMEX）：5％
            amazon_price_match = re.search(r'🉐.*?(\d{1,3}(?:,\d{3})*)（Amazon[・AMEX]*）：', content, re.DOTALL)
            if not amazon_price_match:
                print("Amazon価格抽出失敗")
                return None
            amazon_price = int(amazon_price_match.group(1).replace(',', ''))
            
            # 参考価格リスト抽出
            reference_prices = self.extract_reference_prices(content)
            if len(reference_prices) < 2:
                print(f"参考価格抽出失敗: {len(reference_prices)}個しか見つかりません")
                return None
            
            # Xリンク抽出
            x_link_match = re.search(r'<https://x\.com/[^>]+>', content)
            x_link = x_link_match.group(0) if x_link_match else ""
            
            # パターン判定
            pattern = self.detect_pattern(content)
            
            return {
                'product_name': product_name,
                'jan_code': jan_code,
                'purchase_count': purchase_count,
                'amazon_price': amazon_price,
                'reference_prices': reference_prices,
                'x_link': x_link,
                'pattern': pattern
            }
            
        except Exception as e:
            print(f"解析エラー: {e}")
            return None
    
    def extract_reference_prices(self, content: str) -> List[int]:
        """参考価格リストを抽出"""
        prices = []
        # 「JANコード 〇〇 の参考価格」以降を抽出
        reference_section = re.search(r'JANコード \d+ の参考価格(.*?)(?=\n\n|\Z)', content, re.DOTALL)
        if reference_section:
            price_lines = reference_section.group(1).strip().split('\n')
            for line in price_lines:
                price_match = re.search(r'(\d{1,3}(?:,\d{3})*)円', line)
                if price_match:
                    price = int(price_match.group(1).replace(',', ''))
                    prices.append(price)
        
        return sorted(prices, reverse=True)
    
    def detect_pattern(self, content: str) -> int:
        """パターンを検出"""
        if "前回投稿時よりお得度上昇してます💹" in content:
            return 1  # お得度上昇
        elif "在庫復活してる可能性あり🎉" in content:
            return 2  # 在庫復活
        else:
            return 3  # メンバー募集
    
    def check_profit(self, data: Dict) -> bool:
        """利益判定ロジック"""
        reference_prices = data['reference_prices']
        amazon_price = data['amazon_price']
        
        if len(reference_prices) < 2:
            return False
        
        # 1番目と2番目の参考価格を取得（降順ソート済み）
        first_price = reference_prices[0]   # 最高価格
        second_price = reference_prices[1]  # 2番目の価格
        
        # 参考価格の差額を計算
        price_difference = first_price - second_price
        
        # Amazon価格から差額を差し引く
        profit = amazon_price - price_difference
        
        # 結果がプラスなら利益あり
        return profit > 0
    
    async def post_message(self, data: Dict):
        """投稿処理"""
        try:
            # まずget_channelで試行
            post_channel = self.get_channel(self.post_channel_id)
            print(f"投稿チャンネル取得試行 (get_channel): {self.post_channel_id}")
            
            # get_channelで取得できない場合、fetch_channelを使用
            if not post_channel:
                print("get_channelで取得失敗。fetch_channelで再試行...")
                try:
                    post_channel = await self.fetch_channel(self.post_channel_id)
                    print(f"fetch_channelで取得成功: {post_channel.name}")
                except discord.NotFound:
                    print(f"エラー: チャンネルID {self.post_channel_id} が見つかりません")
                    print("ボットが参加しているサーバーとチャンネル:")
                    for guild in self.guilds:
                        print(f"  サーバー: {guild.name} (ID: {guild.id})")
                        for channel in guild.text_channels:
                            print(f"    - {channel.name} (ID: {channel.id})")
                    return
                except discord.Forbidden:
                    print(f"エラー: チャンネルID {self.post_channel_id} へのアクセス権限がありません")
                    print("必要な権限: メッセージを送信、埋め込みリンク")
                    return
                except Exception as e:
                    print(f"fetch_channel エラー: {e}")
                    return
            else:
                print(f"投稿チャンネル取得成功: {post_channel.name} (サーバー: {post_channel.guild.name})")
            
            # 投稿1: 商品情報
            message1 = self.format_product_message(data)
            print(f"メッセージ1を送信中... (長さ: {len(message1)} 文字)")
            await post_channel.send(message1)
            print("メッセージ1送信完了")
            
            # 0.1秒待機（リアルタイム性向上）
            await asyncio.sleep(0.1)
            
            # 投稿2: Xリンク
            if data['x_link']:
                message2 = f"{data['x_link']}\n￣￣￣￣￣￣￣￣￣￣￣￣￣￣￣"
                print(f"メッセージ2を送信中...")
                await post_channel.send(message2)
                print("メッセージ2送信完了")
            
            print("投稿完了")
            
        except discord.HTTPException as e:
            print(f"投稿エラー (HTTP): ステータスコード {e.status}, メッセージ: {e.text}")
            import traceback
            traceback.print_exc()
            await self.handle_error("投稿処理", e)
        except Exception as e:
            print(f"投稿エラー: {e}")
            import traceback
            traceback.print_exc()
            await self.handle_error("投稿処理", e)
    
    async def handle_error(self, operation: str, error: Exception):
        """エラーハンドリングと自動復帰"""
        self.retry_count += 1
        print(f"{operation}でエラーが発生しました (試行回数: {self.retry_count}/{self.max_retries})")
        print(f"エラー詳細: {error}")
        
        if self.retry_count >= self.max_retries:
            print("最大試行回数に達しました。手動での確認をお願いします。")
            # エラー通知を投稿（無効化）
            # await self.send_error_notification(operation, error)
            self.retry_count = 0
            # 短時間待機でリアルタイム性向上
            await asyncio.sleep(30)  # 30秒待機
        else:
            # 短い待機時間でリアルタイム性向上
            wait_time = min(2 ** self.retry_count, 30)  # 最大30秒
            print(f"{wait_time}秒後にリトライします...")
            await asyncio.sleep(wait_time)
    
    async def send_error_notification(self, operation: str, error: Exception):
        """エラー通知を投稿"""
        try:
            post_channel = self.get_channel(self.post_channel_id)
            if not post_channel:
                try:
                    post_channel = await self.fetch_channel(self.post_channel_id)
                except Exception as e:
                    print(f"エラー通知: チャンネル取得失敗 ({e})")
                    return
            
            if post_channel:
                current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                embed = discord.Embed(
                    title="❌ Amazon監視BOT エラー",
                    description=f"エラーが発生しました\n時刻: {current_time}",
                    color=0xff0000
                )
                embed.add_field(
                    name="操作", 
                    value=operation, 
                    inline=False
                )
                embed.add_field(
                    name="エラー", 
                    value=str(error)[:1000],  # 長すぎる場合は切り詰め
                    inline=False
                )
                await post_channel.send(embed=embed)
                print("エラー通知を投稿しました")
        except Exception as e:
            print(f"エラー通知の投稿に失敗: {e}")
    
    async def periodic_notification_task(self):
        """定期通知タスク"""
        while True:
            try:
                current_time = datetime.now().time()
                current_date = datetime.now().date()
                
                # 今日の通知時間をチェック
                for notification_time in self.notification_times:
                    # 通知時間の5分前から5分後までをチェック
                    time_diff = abs((datetime.combine(current_date, current_time) - 
                                   datetime.combine(current_date, notification_time)).total_seconds())
                    
                    # 5分以内で、まだ今日の通知を送信していない場合
                    if time_diff <= 300 and self.last_notification_date != current_date:
                        await self.send_status_notification()
                        self.last_notification_date = current_date
                        print(f"定期通知を送信しました: {current_time}")
                        break
                
                # 1分ごとにチェック
                await asyncio.sleep(60)
                
            except Exception as e:
                print(f"定期通知タスクエラー: {e}")
                await asyncio.sleep(60)
    
    async def send_status_notification(self):
        """起動状態通知を投稿"""
        try:
            post_channel = self.get_channel(self.post_channel_id)
            if not post_channel:
                try:
                    post_channel = await self.fetch_channel(self.post_channel_id)
                except Exception as e:
                    print(f"定期通知: チャンネル取得失敗 ({e})")
                    return
            
            if post_channel:
                current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                embed = discord.Embed(
                    title="🟢 Amazon監視BOT 稼働中",
                    description=f"正常に監視を継続しています\n時刻: {current_time}",
                    color=0x00ff00
                )
                embed.add_field(
                    name="監視チャンネル", 
                    value=f"<#{self.monitor_channel_id}>", 
                    inline=True
                )
                embed.add_field(
                    name="投稿チャンネル", 
                    value=f"<#{self.post_channel_id}>", 
                    inline=True
                )
                await post_channel.send(embed=embed)
                print("定期通知を投稿しました")
        except Exception as e:
            print(f"定期通知エラー: {e}")
    
    def format_product_message(self, data: Dict) -> str:
        """商品情報メッセージのフォーマット"""
        product_name = data['product_name']
        jan_code = data['jan_code']
        purchase_count = data['purchase_count']
        reference_prices = data['reference_prices']
        pattern = data['pattern']
        
        # 商品名とパターン文を表示
        if pattern == 1:
            message = f"{product_name}\n✅ お得度上昇しています！✨\n\n"
        elif pattern == 2:
            message = f"{product_name}\n✅ 在庫復活しています！✨\n\n"
        else:
            message = f"{product_name}\n\n"
        
        # 購入可能数
        if purchase_count:
            message += f"🛒 個人・ビジネス各{purchase_count}個まで購入可能📦️✨\n"
        else:
            message += "🛒 個人・ビジネス垢でそれぞれ購入可能📦️✨\n"
        
        message += "🛒 本投稿時点でカート追加可能を確認済み\n"
        
        # 参考価格リスト（装飾版）
        message += "━━━━━━━━━━━━━━━━━━━━\n"
        message += f"📚 参考価格（JANコード: {jan_code}）\n"
        message += "━━━━━━━━━━━━━━━━━━━━\n"
        
        # 順位付きで価格を表示
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for i, price in enumerate(reference_prices[:10]):  # 最大10個まで
            medal = medals[i] if i < len(medals) else f"{i+1}️⃣"
            message += f"    {medal} {price:,}円\n"
        
        message += "\n"
        
        # パターン3（メンバー募集）の場合
        if pattern == 3:
            message += "🐇メンバーさん募集🐇\n\n"
            message += "お得商品情報の『参考元📚️』を詳しく知りたいというご要望にお応えし、専用コミュニティを開設しました🤖\n\n"
            message += "📝 申し込みはこちら\n"
            message += "※完全無料・招待制\n"
            message += "https://docs.google.com/forms/d/e/1FAIpQLSfgNP9zlcrepn_5OjJGnv6gDv3ftRUtNm_BYGJToB2keDbRBg/viewform\n\n"
        
        # 生成時刻
        current_time = datetime.now().strftime("%H:%M")
        message += f"🕐 {current_time}"
        
        return message

async def main():
    bot = AmazonMonitorBot()
    
    while True:
        try:
            await bot.start(bot.config['discord_token'])
        except Exception as e:
            print(f"BOT起動エラー: {e}")
            bot.retry_count += 1
            
            if bot.retry_count >= bot.max_retries:
                print("最大試行回数に達しました。2分後に再起動します。")
                await asyncio.sleep(120)  # 2分待機
                bot.retry_count = 0
            else:
                # 短い待機時間でリアルタイム性向上
                wait_time = min(2 ** bot.retry_count, 60)  # 最大1分
                print(f"{wait_time}秒後に再起動します...")
                await asyncio.sleep(wait_time)

if __name__ == "__main__":
    asyncio.run(main())
