import discord
from discord import app_commands
import csv
from cynthia.utils.namespace import Namespace


class PokemonDB:
    def __init__(self, client=None):
        self.pokemon_data = Namespace()
        csv_path = "/raidarchive/cynthia_drive/pokemonDB_dataset.csv"
        with open(csv_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                name = row["Pokemon"]
                self.pokemon_data[name] = Namespace(row)

    def apps(self):
        @app_commands.command()
        async def pokemon(interaction: discord.Interaction, species: str):
            species = species.replace("_", " ")
            if species not in self.pokemon_data:
                await interaction.response.send_message("Invalid species.")
                return
            pokemon_info = self.pokemon_data[species]
            embed = discord.Embed(
                title=pokemon_info.Pokemon, description=pokemon_info.Species
            )
            embed.add_field(name="Type", value=pokemon_info.Type)
            embed.add_field(name="Abilities", value=pokemon_info.Abilities)
            embed.add_field(name="Catch Rate", value=pokemon_info.Catch_Rate)
            embed.add_field(name="EV Yield", value=pokemon_info.EV_Yield)

            await interaction.response.send_message(embed=embed)

        @app_commands.command()
        async def ev(interaction: discord.Interaction, species: str):
            species = species.replace("_", " ")
            if species not in self.pokemon_data:
                await interaction.response.send_message("Invalid species.")
                return
            pokemon_info = self.pokemon_data[species]
            await interaction.response.send_message(
                f"**{pokemon_info.Pokemon}** yields {pokemon_info.EV_Yield}"
            )

        @pokemon.autocomplete("species")
        @ev.autocomplete("species")
        async def pokemon_autocomplete(interaction: discord.Interaction, current: str):
            current = current.replace("_", " ")
            choices = [
                app_commands.Choice(name=species, value=species)
                for species in self.pokemon_data.keys()
                if current.lower() in species.lower()
            ]
            return choices[:25]

        return (pokemon, ev)


__application__ = PokemonDB
