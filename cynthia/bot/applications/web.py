import discord
from discord import app_commands
from rapidfuzz import process
from cynthia.utils.namespace import Namespace
import logging
import requests
import re
import json

logging.getLogger("urllib3").setLevel(logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def format_text(string, upgraded=False):
    string = re.sub(
        r"\[(?P<a>[^\|]*)\|(?P<b>[^\]]*)\]",
        r"\g<b>" if upgraded else r"\g<a>",
        string,
        flags=re.MULTILINE,
    )
    string = string.replace("<br>", "\n")
    string = string.replace("@IE", "🔴")
    string = string.replace("@SE", "🟢")
    string = string.replace("@RE", "🟠")
    string = string.replace("@NE", "🟣")
    string = string.replace("@DE", "🔵")
    string = string.replace("@ST", "⭐")
    string = re.sub(r"\$([a-zA-Z]+)", r"**\g<1>**", string)
    return string


class Compendium:
    base_url = "https://slaythespire.wiki.gg/wiki/"
    img_url = "https://slaythespire.wiki.gg/images/"
    card_data_urls = [
        "https://slaythespire.wiki.gg/wiki/Module:Cards/data?action=raw",
    ] + [
        f"https://slaythespire.wiki.gg/wiki/Module:Cards/StS2_data/{character}?action=raw"
        for character in [
            "Ironclad",
            "Silent",
            "Regent",
            "Necrobinder",
            "Defect",
            "Colorless",
        ]
    ]
    relic_data_url = "https://slaythespire.wiki.gg/wiki/Module:Relics/data?action=raw"

    COLORS = Namespace(
        {
            "Red": 0x922929,
            "Ironclad": 0x922929,
            "Green": 0x437B33,
            "Silent": 0x437B33,
            "Regent": 0x97560B,
            "Blue": 0x256888,
            "Defect": 0x258688,
            "Purple": 0x904258,
            "Necrobinder": 0x904258,
            "Colorless": 0x595959,
        }
    )

    def __init__(self, client):
        self.drive = client.drive
        self.card_data = {}
        self.relic_data = {}
        self.build_card_data()
        self.build_relic_data()

    def build_card_data(self):
        if self.drive.exists("card_data.json", is_file=True):
            with self.drive.open("card_data.json", "r") as f:
                self.card_data = json.load(f)

        for url in self.card_data_urls:
            response = requests.get(url)
            if response.status_code == 200:
                card_data = response.text
                card_data = card_data.replace("return {", "{")
                card_data = re.sub(
                    r"^\s*(?=[a-zA-Z])", '"', card_data, flags=re.MULTILINE
                )
                card_data = re.sub(r"^\s*\[", "", card_data, flags=re.MULTILINE)
                card_data = re.sub(r", --.*$", ",", card_data, flags=re.MULTILINE)
                card_data = card_data.replace('"]', "")
                card_data = card_data.replace(" = ", '": ')
                card_data = card_data.replace("\t", "")

                data_lines = []

                for line in card_data.split("\n"):
                    if "Traits" in line:
                        continue
                    data_lines.append(line)

                card_data = "\n".join(data_lines)

                card_data = re.sub(r",\n\s*}", "\n}", card_data, flags=re.MULTILINE)

                self.card_data |= json.loads(card_data)

        if self.drive.enabled:
            with self.drive.open("card_data.json", "w") as f:
                json.dump(self.card_data, f)

    def build_relic_data(self):
        if self.drive.exists("relic_data.json", is_file=True):
            with self.drive.open("relic_data.json", "r") as f:
                self.relic_data = json.load(f)
        response = requests.get(self.relic_data_url)
        if response.status_code == 200:
            relic_data = response.text
            relic_data = relic_data.replace("return {", "{")
            relic_data = re.sub(
                r"^\s*(?=[a-zA-Z])", '"', relic_data, flags=re.MULTILINE
            )
            relic_data = re.sub(r"^\s*\[", "", relic_data, flags=re.MULTILINE)
            relic_data = relic_data.replace('"]', "")
            relic_data = relic_data.replace(" = ", '": ')
            relic_data = re.sub(
                r":\s*{\s*(?=[a-zA-Z])", ': { "', relic_data, flags=re.MULTILINE
            )
            relic_data = relic_data.replace("\t", "")

            data_lines = []

            for line in relic_data.split("\n"):
                if "Traits" in line:
                    continue
                data_lines.append(line)

            relic_data = "\n".join(data_lines)

            relic_data = re.sub(r",\n\s*}", "\n}", relic_data, flags=re.MULTILINE)

            self.relic_data |= json.loads(relic_data)

        if self.drive.enabled:
            with self.drive.open("relic_data.json", "w") as f:
                json.dump(self.relic_data, f)

    def apps(self):
        @app_commands.command()
        async def compendium_reload(interaction):
            await interaction.response.defer(ephemeral=True)
            self.build_card_data()
            self.build_relic_data()

            await interaction.response.followup("Reloaded compendium data.")

        @app_commands.command()
        async def compendium(interaction, query: str):
            if query in self.card_data.keys():
                card_info = self.card_data[query]

                embed = discord.Embed(
                    title=query,
                    url=self.base_url + query.replace(" ", "_"),
                    description=format_text(card_info["Text"]),
                    colour=self.COLORS[card_info["Color"]],
                )
                embed.set_footer(text=f"{card_info['Rarity']} {card_info['Type']}")
                embed.set_image(url=self.img_url + card_info["Image"])

                class SmithView(discord.ui.View):
                    def __init__(self, parent, card_info):
                        super().__init__()
                        self.parent = parent
                        self.card_info = card_info
                        self.state = False
                        self.message = None

                    async def on_timeout(self):
                        if self.message:
                            try:
                               await self.message.edit(embed=_embed, view=None)
                            except discord.HTTPException:
                                pass

                    @discord.ui.button(
                        label="Smith", emoji="🔨", style=discord.ButtonStyle.gray
                    )
                    async def toggle_button(self, interaction, button):
                        self.state = not self.state

                        _embed = interaction.message.embeds[0]

                        if self.state:
                            button.style = discord.ButtonStyle.green
                            _embed.set_image(
                                url=self.parent.img_url
                                + self.card_info["Image"].replace(".png", "Plus.png")
                            )
                            _embed.description = format_text(
                                self.card_info["Text"], upgraded=True
                            )
                        else:
                            button.style = discord.ButtonStyle.gray
                            _embed.set_image(
                                url=self.parent.img_url + self.card_info["Image"]
                            )
                            _embed.description = format_text(self.card_info["Text"])

                        await interaction.response.edit_message(
                            embed=_embed,
                            view=self,
                        )
                        self.message = await interaction.original_response()

                view = SmithView(self, card_info)
                message = await interaction.response.send_message(
                    embed=embed,
                    view=view,
                )
                view.message = await interaction.original_response()

            elif query in self.relic_data.keys():
                relic_info = self.relic_data[query]
                embed = discord.Embed(
                    title=query,
                    url=self.base_url + query.replace(" ", "_"),
                    description=format_text(relic_info["Description"])
                    + "\n*"
                    + relic_info["Flavor"]
                    + "*",
                    colour=self.COLORS[relic_info.get("Character", "Colorless")],
                )
                embed.set_thumbnail(url=self.img_url + relic_info["Image"])
                embed.set_footer(text=f"{relic_info['Rarity']} Relic")
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message(
                    "No card or relic found with that name."
                )

        @compendium.autocomplete("query")
        async def query_autocomplete(interaction, current):
            matches = process.extract(
                current, self.card_data.keys() | self.relic_data.keys(), limit=10
            )
            choices = [
                app_commands.Choice(name=query[0], value=query[0]) for query in matches
            ]
            return choices[:10]

        return compendium, compendium_reload


__application__ = Compendium
