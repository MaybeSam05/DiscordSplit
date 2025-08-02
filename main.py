import discord
from discord import app_commands
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import json
from flask import Flask
import threading
import random
import openai
import aiohttp

load_dotenv()
token = os.getenv("DISCORD_TOKEN")
openai.api_key = os.getenv("OPENAI_API_KEY")

handler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

EXPENSES_FILE = "expenses.json"
BALANCES_FILE = "balances.json"
GROUP_MEMBERS_FILE = "group_members.json"

class SplitwiseBot:
    def __init__(self):
        self.expenses = self.load_expenses()
        self.balances = self.load_balances()
        self.group_members = self.load_group_members()
    
    def load_expenses(self) -> Dict:
        try:
            with open(EXPENSES_FILE, 'r') as f:
                data = json.load(f)
                converted_data = {}
                for guild_id, expenses in data.items():
                    converted_expenses = []
                    for expense in expenses:
                        converted_expense = expense.copy()
                        converted_expense['payer_id'] = int(expense['payer_id'])
                        converted_expense['split_with'] = [int(user_id) for user_id in expense['split_with']]
                        converted_expenses.append(converted_expense)
                    converted_data[guild_id] = converted_expenses
                return converted_data
        except FileNotFoundError:
            return {}
    
    def save_expenses(self):
        serializable_expenses = {}
        for guild_id, expenses in self.expenses.items():
            serializable_expenses[guild_id] = []
            for expense in expenses:
                serializable_expense = expense.copy()
                serializable_expense['payer_id'] = str(expense['payer_id'])
                serializable_expense['split_with'] = [str(user_id) for user_id in expense['split_with']]
                serializable_expenses[guild_id].append(serializable_expense)
        
        with open(EXPENSES_FILE, 'w') as f:
            json.dump(serializable_expenses, f, indent=2)
    
    def load_balances(self) -> Dict:
        try:
            with open(BALANCES_FILE, 'r') as f:
                data = json.load(f)
                converted_data = {}
                for guild_id, balances in data.items():
                    converted_data[guild_id] = {int(user_id): balance for user_id, balance in balances.items()}
                return converted_data
        except FileNotFoundError:
            return {}
    
    def save_balances(self):
        serializable_balances = {}
        for guild_id, balances in self.balances.items():
            serializable_balances[guild_id] = {str(user_id): balance for user_id, balance in balances.items()}
        
        with open(BALANCES_FILE, 'w') as f:
            json.dump(serializable_balances, f, indent=2)
    
    def load_group_members(self) -> Dict:
        try:
            with open(GROUP_MEMBERS_FILE, 'r') as f:
                data = json.load(f)
                converted_data = {}
                for guild_id, members in data.items():
                    converted_data[guild_id] = [int(member_id) for member_id in members]
                return converted_data
        except FileNotFoundError:
            return {}
    
    def save_group_members(self):
        serializable_members = {}
        for guild_id, members in self.group_members.items():
            serializable_members[guild_id] = [str(member_id) for member_id in members]
        
        with open(GROUP_MEMBERS_FILE, 'w') as f:
            json.dump(serializable_members, f, indent=2)
    
    def initialize_group(self, guild_id: str, member_ids: List[str]) -> Tuple[bool, str]:
        guild_id = str(guild_id)
        
        member_ids_int = [int(member_id) for member_id in member_ids]
        
        if guild_id in self.group_members:
            return False, "Group already initialized. Use /reset to reinitialize."
        
        self.group_members[guild_id] = member_ids_int
        
        if guild_id not in self.balances:
            self.balances[guild_id] = {}
        
        for member_id in member_ids_int:
            self.balances[guild_id][member_id] = 0
        
        if guild_id not in self.expenses:
            self.expenses[guild_id] = []
        
        self.save_group_members()
        self.save_balances()
        
        return True, f"Group initialized with {len(member_ids_int)} members"
    
    def reset_group(self, guild_id: str) -> Tuple[bool, str]:
        guild_id = str(guild_id)
        
        if guild_id not in self.group_members:
            return False, "Group not initialized. Use /init to initialize."
        
        if guild_id in self.group_members:
            del self.group_members[guild_id]
        if guild_id in self.balances:
            del self.balances[guild_id]
        if guild_id in self.expenses:
            del self.expenses[guild_id]
        
        self.save_group_members()
        self.save_balances()
        self.save_expenses()
        
        return True, "Group reset successfully. Use /init to reinitialize."
    
    def get_group_members(self, guild_id: str) -> List[int]:
        guild_id = str(guild_id)
        return self.group_members.get(guild_id, [])
    
    def is_group_initialized(self, guild_id: str) -> bool:
        guild_id = str(guild_id)
        return guild_id in self.group_members and len(self.group_members[guild_id]) > 0
    
    def add_expense(self, guild_id: str, payer_id: str, amount: float, description: str, split_with: List[str]):
        guild_id = str(guild_id)
        payer_id = int(payer_id)
        
        if guild_id not in self.expenses:
            self.expenses[guild_id] = []
        if guild_id not in self.balances:
            self.balances[guild_id] = {}
        
        split_with_ints = [int(user_id) for user_id in split_with]
        
        expense = {
            "id": len(self.expenses[guild_id]) + 1,
            "payer_id": payer_id,
            "amount": amount,
            "description": description,
            "split_with": split_with_ints,
            "timestamp": datetime.now().isoformat(),
            "per_person": amount / len(split_with_ints) if split_with_ints else 0
        }
        
        self.expenses[guild_id].append(expense)
        
        if payer_id not in self.balances[guild_id]:
            self.balances[guild_id][payer_id] = 0
        self.balances[guild_id][payer_id] += amount
        
        for person_id in split_with_ints:
            if person_id not in self.balances[guild_id]:
                self.balances[guild_id][person_id] = 0
            self.balances[guild_id][person_id] -= expense["per_person"]
        
        self.save_expenses()
        self.save_balances()
        return expense
    
    def get_balances(self, guild_id: str) -> Dict:
        guild_id = str(guild_id)
        balances = self.balances.get(guild_id, {})
        return balances
    
    def get_expenses(self, guild_id: str) -> List:
        guild_id = str(guild_id)
        return self.expenses.get(guild_id, [])
    
    def settle_debt(self, guild_id: str, from_user_id: str, to_user_id: str, amount: float):
        guild_id = str(guild_id)
        from_user_id = int(from_user_id)
        to_user_id = int(to_user_id)
        
        if guild_id not in self.balances:
            return False, "No balances found for this server"
        
        if from_user_id not in self.balances[guild_id] or to_user_id not in self.balances[guild_id]:
            return False, "One or both users not found in balances"
        
        from_balance = self.balances[guild_id][from_user_id]
        to_balance = self.balances[guild_id][to_user_id]
        
        if from_balance >= 0:
            return False, f"<@{str(from_user_id)}> doesn't owe any money (balance: ${from_balance:.2f})"
        
        if to_balance <= 0:
            return False, f"<@{str(to_user_id)}> isn't owed any money (balance: ${to_balance:.2f})"
        
        max_settlement = min(abs(from_balance), to_balance)
        
        if amount > max_settlement:
            return False, f"Amount too high. Maximum settlement possible: ${max_settlement:.2f}"
        
        self.balances[guild_id][from_user_id] += amount
        self.balances[guild_id][to_user_id] -= amount
        
        self.save_balances()
        return True, f"Settled ${amount:.2f} from <@{str(from_user_id)}> to <@{str(to_user_id)}>"
    
    def remove_expense(self, guild_id: str, description: str) -> Tuple[bool, str]:
        guild_id = str(guild_id)
        
        if guild_id not in self.expenses:
            return False, "No expenses found for this server"
        
        expense_to_remove = None
        expense_index = -1
        
        for i, expense in enumerate(self.expenses[guild_id]):
            if expense['description'].lower() == description.lower():
                expense_to_remove = expense
                expense_index = i
                break
        
        if not expense_to_remove:
            return False, f"No expense found with description: {description}"
        
        payer_id = int(expense_to_remove['payer_id'])
        split_with = [int(user_id) for user_id in expense_to_remove['split_with']]
        amount = expense_to_remove['amount']
        per_person = expense_to_remove['per_person']
        
        if payer_id in self.balances[guild_id]:
            self.balances[guild_id][payer_id] -= amount
        
        for person_id in split_with:
            if person_id in self.balances[guild_id]:
                self.balances[guild_id][person_id] += per_person
        
        self.expenses[guild_id].pop(expense_index)
        
        for i, expense in enumerate(self.expenses[guild_id]):
            expense['id'] = i + 1
        
        self.save_expenses()
        self.save_balances()
        
        return True, f"Removed expense: {expense_to_remove['description']} (${amount:.2f})"

splitwise = SplitwiseBot()

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    app.run(host='0.0.0.0', port=10000)

flask_thread = threading.Thread(target=run_flask)
flask_thread.daemon = True
flask_thread.start()

@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

async def generate_chat_response(user_name: str, user_message: str) -> str:
    try:
        with open('chats.txt', 'r', encoding='utf-8') as f:
            chat_content = f.read()
        
        prompt = f"""Based on this chat log, generate a funny 1-sentence response that someone with this texting style and slang would say. The response should be directed at {user_name} and should match the casual, slang-heavy tone of the chat.

User's message: "{user_message}"

Chat content: {chat_content}

Generate a funny response to what {user_name} said:"""
        
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a gen-z slang bot that generates responses in the style of the chat log. Keep responses as a 18 year old tuff teenager would say,casual, use slang, don't surround your response in quotes, don't use any emojis, say goofy shit, be freaky, dont use proper grammar, be sus, say slang like bro or use the ninja emoji often to refer to people, don't be too serious."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=50,
            temperature=0.8
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating response: {e}")
        fallback_responses = [
            f"Hi {user_name}, I love khicidi!",
            f"Sorry can't talk right now {user_name}, I have to go to Pennsylvania.",
            f"Alc? Did {user_name} say Alc???"
        ]
        return random.choice(fallback_responses)

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    if bot.user.mentioned_in(message):
        response = await generate_chat_response(message.author.display_name, message.content)
        await message.channel.send(response)
    
    await bot.process_commands(message)

@bot.tree.command(name="init", description="Initialize the group with all members")
@app_commands.describe(
    members="Mention all members in the group"
)
async def initialize_group(interaction: discord.Interaction, members: str):
    member_ids = []
    for word in members.split():
        if word.startswith('<@') and word.endswith('>'):
            user_id = word[2:-1]
            if user_id.startswith('!'):
                user_id = user_id[1:]
            member_ids.append(user_id)
    
    command_user_id = str(interaction.user.id)
    if command_user_id not in member_ids:
        member_ids.append(command_user_id)
    
    if len(member_ids) < 2:
        await interaction.response.send_message("❌ Please mention at least one other person to create a group", ephemeral=True)
        return
    
    success, message = splitwise.initialize_group(
        guild_id=interaction.guild_id,
        member_ids=member_ids
    )
    
    if success:
        members_text = ", ".join([f"<@{str(member_id)}>" for member_id in member_ids])
        embed = discord.Embed(
            title="✅ Group Initialized",
            description=message,
            color=discord.Color.green()
        )
        embed.add_field(name="Members", value=members_text, inline=False)
        embed.set_footer(text="You can now use /add to add expenses that will be split among all members")
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(f"❌ {message}", ephemeral=True)

@bot.tree.command(name="reset", description="Reset the group (clear all data)")
async def reset_group(interaction: discord.Interaction):
    success, message = splitwise.reset_group(interaction.guild_id)
    
    if success:
        embed = discord.Embed(
            title="🔄 Group Reset",
            description=message,
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(f"❌ {message}", ephemeral=True)

@bot.tree.command(name="add", description="Add an expense")
@app_commands.describe(
    amount="Amount of the expense",
    description="Description of the expense"
)
async def add_expense(interaction: discord.Interaction, amount: float, description: str):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be greater than 0", ephemeral=True)
        return
    
    if not splitwise.is_group_initialized(interaction.guild_id):
        await interaction.response.send_message("❌ Group not initialized. Please use /init first to set up the group members.", ephemeral=True)
        return
    
    group_members = splitwise.get_group_members(interaction.guild_id)
    if not group_members:
        await interaction.response.send_message("❌ No group members found. Please use /init to set up the group.", ephemeral=True)
        return
    
    member_ids = [str(member_id) for member_id in group_members]
    
    expense = splitwise.add_expense(
        guild_id=interaction.guild_id,
        payer_id=interaction.user.id,
        amount=amount,
        description=description,
        split_with=member_ids
    )
    
    members_text = ", ".join([f"<@{str(member_id)}>" for member_id in group_members])
    embed = discord.Embed(
        title="💰 Expense Added",
        description=f"**{description}**",
        color=discord.Color.green()
    )
    embed.add_field(name="Amount", value=f"${amount:.2f}", inline=True)
    embed.add_field(name="Paid by", value=f"<@{str(interaction.user.id)}>", inline=True)
    embed.add_field(name="Split with", value=members_text, inline=False)
    embed.add_field(name="Per person", value=f"${expense['per_person']:.2f}", inline=True)
    embed.set_footer(text=f"Expense ID: {expense['id']}")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="check", description="Check balances for all members")
async def check_balances(interaction: discord.Interaction):
    if not splitwise.is_group_initialized(interaction.guild_id):
        await interaction.response.send_message("❌ Group not initialized. Please use /init first to set up the group members.", ephemeral=True)
        return
    
    balances = splitwise.get_balances(interaction.guild_id)
    
    if not balances:
        await interaction.response.send_message("📊 No expenses recorded yet!", ephemeral=True)
        return
    
    debtors = {}
    creditors = {}
    
    for user_id, balance in balances.items():
        if balance < 0:
            debtors[user_id] = abs(balance)
        elif balance > 0:
            creditors[user_id] = balance
    
    embed = discord.Embed(
        title="💰 Who Owes Whom",
        description="Current debt relationships",
        color=discord.Color.blue()
    )
    
    if not debtors or not creditors:
        if not debtors and not creditors:
            embed.description = "✅ All balances are settled!"
        else:
            embed.description = "No active debts to settle"
    else:
        embed.add_field(
            name="📊 Individual Balances",
            value="\n".join([f"<@{str(user_id)}>: ${balance:.2f}" for user_id, balance in balances.items()]),
            inline=False
        )
        
        debt_relationships = []
        user_ids = list(balances.keys())
        
        for i, user1_id in enumerate(user_ids):
            for user2_id in user_ids[i+1:]:
                user1_balance = balances[user1_id]
                user2_balance = balances[user2_id]
                
                if user1_balance < 0 and user2_balance > 0:
                    net_debt = min(abs(user1_balance), user2_balance)
                    debt_relationships.append(f"<@{str(user1_id)}> owes <@{str(user2_id)}> ${net_debt:.2f}")
                elif user2_balance < 0 and user1_balance > 0:
                    net_debt = min(abs(user2_balance), user1_balance)
                    debt_relationships.append(f"<@{str(user2_id)}> owes <@{str(user1_id)}> ${net_debt:.2f}")
        
        if debt_relationships:
            embed.add_field(
                name="💸 Net Debts",
                value="\n".join(debt_relationships),
                inline=False
            )
        else:
            embed.add_field(
                name="💸 Net Debts",
                value="No net debts between individual users",
                inline=False
            )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="settle", description="Settle a debt between two users")
@app_commands.describe(
    to_user="User to pay money to",
    amount="Amount to pay"
)
async def settle_debt(interaction: discord.Interaction, to_user: discord.Member, amount: float):
    if not splitwise.is_group_initialized(interaction.guild_id):
        await interaction.response.send_message("❌ Group not initialized. Please use /init first to set up the group members.", ephemeral=True)
        return
    
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be greater than 0", ephemeral=True)
        return
    
    if to_user.id == interaction.user.id:
        await interaction.response.send_message("❌ You can't settle with yourself", ephemeral=True)
        return
    
    balances = splitwise.get_balances(interaction.guild_id)
    from_balance = balances.get(interaction.user.id, 0)
    to_balance = balances.get(to_user.id, 0)
    
    success, message = splitwise.settle_debt(
        guild_id=interaction.guild_id,
        from_user_id=interaction.user.id,
        to_user_id=to_user.id,
        amount=amount
    )
    
    if success:
        updated_balances = splitwise.get_balances(interaction.guild_id)
        new_from_balance = updated_balances.get(interaction.user.id, 0)
        new_to_balance = updated_balances.get(to_user.id, 0)
        
        embed = discord.Embed(
            title="✅ Debt Settled",
            description=message,
            color=discord.Color.green()
        )
        embed.add_field(
            name="Previous Balances",
            value=f"<@{str(interaction.user.id)}>: ${from_balance:.2f}\n<@{str(to_user.id)}>: ${to_balance:.2f}",
            inline=True
        )
        embed.add_field(
            name="New Balances",
            value=f"<@{str(interaction.user.id)}>: ${new_from_balance:.2f}\n<@{str(to_user.id)}>: ${new_to_balance:.2f}",
            inline=True
        )
        await interaction.response.send_message(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Settlement Failed",
            description=message,
            color=discord.Color.red()
        )
        embed.add_field(
            name="Current Balances",
            value=f"<@{str(interaction.user.id)}>: ${from_balance:.2f}\n<@{str(to_user.id)}>: ${to_balance:.2f}",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="history", description="View expense history")
async def view_history(interaction: discord.Interaction):
    if not splitwise.is_group_initialized(interaction.guild_id):
        await interaction.response.send_message("❌ Group not initialized. Please use /init first to set up the group members.", ephemeral=True)
        return
    
    expenses = splitwise.get_expenses(interaction.guild_id)
    
    if not expenses:
        await interaction.response.send_message("📋 No expenses recorded yet!", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📋 Expense History",
        description=f"Showing last {min(10, len(expenses))} expenses",
        color=discord.Color.purple()
    )
    
    for expense in expenses[-10:]:
        timestamp = datetime.fromisoformat(expense['timestamp']).strftime("%m/%d %I:%M %p")
        split_with_text = ", ".join([f"<@{str(user_id)}>" for user_id in expense['split_with']])
        
        embed.add_field(
            name=f"#{expense['id']} - {expense['description']} (${expense['amount']:.2f})",
            value=f"Paid by <@{str(expense['payer_id'])}>\nSplit with: {split_with_text}\n{timestamp}",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clear", description="Remove an expense by description")
@app_commands.describe(
    description="Exact description of the expense to remove"
)
async def clear_expense(interaction: discord.Interaction, description: str):
    if not splitwise.is_group_initialized(interaction.guild_id):
        await interaction.response.send_message("❌ Group not initialized. Please use /init first to set up the group members.", ephemeral=True)
        return
    
    if not description.strip():
        await interaction.response.send_message("❌ Please provide a description to remove", ephemeral=True)
        return
    
    success, message = splitwise.remove_expense(
        guild_id=interaction.guild_id,
        description=description
    )
    
    if success:
        embed = discord.Embed(
            title="🗑️ Expense Removed",
            description=message,
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(f"❌ {message}", ephemeral=True)

if __name__ == "__main__":
    bot.run(token)
