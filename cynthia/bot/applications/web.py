"""Application commands backed by game and Pokémon reference data."""

import csv
import json
import logging
import re
from datetime import datetime

import discord
import requests_async as requests
from discord import app_commands
from rapidfuzz import process

from cynthia.utils.auth import is_owner, nonglobal_command
from cynthia.utils.namespace import Namespace

logging.getLogger("httpcore").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Pokémon species CSV expected at the root of the drive
POKEMON_DATASET = "pokemonDB_dataset.csv"


class Compendium:
    """Load, refresh, and persist remote reference datasets."""

    children = []

    def __init__(self, child, client, datasets):
        """Store the drive and remote dataset definitions."""
        self.drive = client.drive
        self.datasets = datasets

    async def __ainit__(self):
        """Build datasets when the application is initialized."""
        await self.build()

    async def build(self):
        """Load each dataset, fetch current data, update it, and save it."""
        for key in self.datasets.keys():
            self.load(key)
            newdata = await getattr(self, f"fetch_{key}_data")()
            self.update(key, newdata)
            self.save(key)

    async def reload(self):
        """Fetch, update, and save each dataset without reloading cached data."""
        for key in self.datasets.keys():
            newdata = await getattr(self, f"fetch_{key}_data")()
            self.update(key, newdata)
            self.save(key)

    def load(self, dataset: str):
        """Load a dataset from drive storage, if a saved file exists."""
        temp = None
        filename = f"compendium/{self.__class__.__name__.lower()}/{dataset}_data.json"
        if self.drive.exists(filename, is_file=True):
            with self.drive.open(filename, "r") as f:
                temp = json.load(f)
        setattr(self, f"{dataset}_data", temp)

    def update(self, dataset, new_data):
        """Merge fetched JSON data and set timestamps for new or changed entries."""
        with open("tmp.json", "w") as f:
            f.write(new_data)
        for key, value in json.loads(new_data).items():
            testdict = getattr(self, f"{dataset}_data", dict()).get(key, dict()).copy()
            testdict["updatetime"] = None
            del testdict["updatetime"]
            if testdict != value:
                getattr(self, f"{dataset}_data")[key] = value

            if getattr(self, f"{dataset}_data")[key].get("updatetime", None) is None:
                getattr(self, f"{dataset}_data")[key]["updatetime"] = (
                    datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
                )

    def save(self, dataset):
        """Persist a dataset when the configured drive is enabled."""
        if self.drive.enabled:
            filename = (
                f"compendium/{self.__class__.__name__.lower()}/{dataset}_data.json"
            )
            with self.drive.open(filename, "w") as f:
                json.dump(getattr(self, f"{dataset}_data", dict()), f)


class STS(Compendium):
    """Fetch Slay the Spire data and expose card and relic lookup commands."""

    base_url = "https://slaythespire.wiki.gg/wiki/"
    img_url = "https://slaythespire.wiki.gg/images/"
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

    @staticmethod
    def format_text(string, upgraded=False):
        """Format wiki markup and icons for Discord embed text."""
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

    def __init__(self, client):
        """Configure card and relic data sources for the compendium."""
        super().__init__(
            self,
            client,
            {
                "card": [
                    "https://slaythespire.wiki.gg/wiki/Module:Cards/data?action=raw",
                ]
                + [
                    f"https://slaythespire.wiki.gg/wiki/Module:Cards/StS2_data/{character}?action=raw"
                    for character in [
                        "Ironclad",
                        "Silent",
                        "Regent",
                        "Necrobinder",
                        "Defect",
                        "Colorless",
                    ]
                ],
                "relic": [
                    "https://slaythespire.wiki.gg/wiki/Module:Relics/StS2_data?action=raw"
                ],
            },
        )

    async def fetch_card_data(self):
        """Fetch and convert card data from the configured wiki modules."""
        for url in self.datasets["card"]:
            response = await requests.get(url)
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
                card_data = re.sub(
                    r'^"local all_data.*$', "{", card_data, flags=re.MULTILINE
                )
                card_data = re.sub(
                    r'""local formatted.*', "", card_data, flags=re.DOTALL
                )

                data_lines = []

                for line in card_data.split("\n"):
                    if "Traits" in line:
                        continue
                    data_lines.append(line)

                card_data = "\n".join(data_lines)

                card_data = re.sub(r",\n\s*}", "\n}", card_data, flags=re.MULTILINE)
                return card_data

    async def fetch_relic_data(self):
        """Fetch and convert relic data from the configured wiki module."""
        response = await requests.get(self.datasets["relic"][0])
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
            relic_data = re.sub(
                r'^"local all_data.*$', "{", relic_data, flags=re.MULTILINE
            )
            relic_data = re.sub(r'""local formatted.*', "", relic_data, flags=re.DOTALL)

            data_lines = []

            for line in relic_data.split("\n"):
                if "Traits" in line:
                    continue
                data_lines.append(line)

            relic_data = "\n".join(data_lines)

            relic_data = re.sub(r",\n\s*}", "\n}", relic_data, flags=re.MULTILINE)

            return relic_data

    def apps(self):
        """Return the Slay the Spire lookup command and autocomplete handler."""

        @app_commands.command()
        @app_commands.default_permissions(send_messages=True)
        @nonglobal_command()
        async def sts(interaction, query: str):
            """Show a matching card or relic in a Discord embed."""
            if query in self.card_data.keys():
                card_info = self.card_data[query]

                embed = discord.Embed(
                    title=query,
                    url=self.base_url + "Slay_the_Spire_2:" + query.replace(" ", "_"),
                    description=STS.format_text(card_info["Text"]),
                    colour=self.COLORS[card_info["Color"]],
                )
                embed.set_footer(
                    text=f"{card_info['Rarity']} {card_info['Type']} (Updated: {card_info['updatetime']})"
                )
                embed.set_image(url=self.img_url + card_info["Image"])

                class SmithView(discord.ui.View):
                    """Interactive view for toggling a card's upgraded details."""

                    def __init__(self, parent, card_info):
                        """Store card data and initialize the upgrade toggle."""
                        super().__init__()
                        self.parent = parent
                        self.card_info = card_info
                        self.state = False
                        self.message = None

                    async def on_timeout(self):
                        """Remove the view from its message when it expires."""
                        if self.message:
                            try:
                                _embed = self.message.embeds[0]
                                await self.message.edit(embed=_embed, view=None)
                            except discord.HTTPException:
                                pass

                    @discord.ui.button(
                        label="Smith", emoji="🔨", style=discord.ButtonStyle.gray
                    )
                    async def toggle_button(self, interaction, button):
                        """Toggle the card between base and upgraded details."""
                        self.state = not self.state

                        _embed = interaction.message.embeds[0]

                        if self.state:
                            button.style = discord.ButtonStyle.green
                            _embed.set_image(
                                url=self.parent.img_url
                                + self.card_info["Image"].replace(".png", "Plus.png")
                            )
                            _embed.description = STS.format_text(
                                self.card_info["Text"], upgraded=True
                            )
                        else:
                            button.style = discord.ButtonStyle.gray
                            _embed.set_image(
                                url=self.parent.img_url + self.card_info["Image"]
                            )
                            _embed.description = STS.format_text(self.card_info["Text"])

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
                    description=STS.format_text(relic_info["Description"])
                    + "\n*"
                    + relic_info["Flavor"]
                    + "*",
                    colour=self.COLORS[relic_info.get("Character", "Colorless")],
                )
                embed.set_thumbnail(url=self.img_url + relic_info["Image"])
                embed.set_footer(
                    text=f"{relic_info['Rarity']} Relic (Updated: {relic_info['updatetime']})"
                )
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message(
                    "No card or relic found with that name."
                )

        @sts.autocomplete("query")
        async def query_autocomplete(interaction, current):
            """Suggest card and relic names matching the query."""
            matches = process.extract(
                current, self.card_data.keys() | self.relic_data.keys(), limit=10
            )
            choices = [
                app_commands.Choice(name=query[0], value=query[0]) for query in matches
            ]
            return choices[:10]

        return (sts,)


class SerebiiParser:
    """Reserved parser type for Serebii reference data."""


class PokemonDB:
    """Load Pokémon reference data and expose species lookup commands."""

    def __init__(self, client=None):
        """Load the Pokémon CSV dataset into a name-indexed mapping."""
        self.pokemon_data = Namespace()

        drive = getattr(client, "drive", None)
        if drive is None or not drive.exists(POKEMON_DATASET, is_file=True):
            logger.warning(
                f"{POKEMON_DATASET} not found on the drive; /pokemon is disabled."
            )
            return

        with open(drive.path(POKEMON_DATASET), newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                name = row["Pokemon"].lower()
                self.pokemon_data[name] = Namespace(row)

    def apps(self):
        """Return Pokémon lookup commands and their species autocomplete."""

        @app_commands.command()
        @app_commands.default_permissions(send_messages=True)
        @nonglobal_command()
        async def pokemon(interaction: discord.Interaction, species: str):
            """Show type, abilities, catch rate, and EV yield for a species."""
            species = species.replace("_", " ")
            if species.lower() not in self.pokemon_data:
                await interaction.response.send_message("Invalid species.")
                return
            pokemon_info = self.pokemon_data[species.lower()]
            embed = discord.Embed(
                title=pokemon_info.Pokemon, description=pokemon_info.Species
            )
            embed.add_field(name="Type", value=pokemon_info.Type)
            embed.add_field(name="Abilities", value=pokemon_info.Abilities)
            embed.add_field(name="Catch Rate", value=pokemon_info.Catch_Rate)
            embed.add_field(name="EV Yield", value=pokemon_info.EV_Yield)

            await interaction.response.send_message(embed=embed)

        @app_commands.command()
        @app_commands.default_permissions(send_messages=True)
        @nonglobal_command()
        async def ev(interaction: discord.Interaction, species: str):
            """Show the EV yield for a Pokémon species."""
            species = species.replace("_", " ")
            if species.lower() not in self.pokemon_data:
                await interaction.response.send_message("Invalid species.")
                return
            pokemon_info = self.pokemon_data[species.lower()]
            await interaction.response.send_message(
                f"**{pokemon_info.Pokemon}** yields {pokemon_info.EV_Yield}"
            )

        @pokemon.autocomplete("species")
        @ev.autocomplete("species")
        async def pokemon_autocomplete(interaction: discord.Interaction, current: str):
            """Suggest Pokémon species matching the query."""
            current = current.replace("_", " ")
            choices = [
                app_commands.Choice(
                    name=self.pokemon_data[species].Pokemon, value=species
                )
                for species in self.pokemon_data.keys()
                if current.lower() in species
            ]
            return choices[:10]

        return (pokemon, ev)


@app_commands.command()
@app_commands.default_permissions(administrator=True)
@is_owner()
@nonglobal_command()
async def compendium_reload(interaction: discord.Interaction):
    """Refresh each registered compendium dataset."""
    await interaction.response.defer(ephemeral=True)
    for child in Compendium.children:
        child.reload()

    await interaction.followup.send("Reloaded compendium data.")


# STS Wiki Broken RN?
__application__ = [PokemonDB]
