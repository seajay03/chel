require("dotenv").config();
const { Client, GatewayIntentBits } = require("discord.js");
const fs = require("fs");

const config = require("./config.json");

// Create bot client
const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.DirectMessages
    ],
    partials: ["CHANNEL"]
});

// Bot ready event
client.once("ready", () => {
    console.log(`✅ Logged in as ${client.user.tag}`);
});

// Listen for messages
client.on("messageCreate", (message) => {
    // Ignore bot messages
    if (message.author.bot) return;

    // Ignore messages without the prefix
    if (!message.content.startsWith(config.prefix)) return;

    const args = message.content.slice(config.prefix.length).trim().split(/ +/);
    const command = args.shift().toLowerCase();

    if (command === "ping") {
        message.reply("🏒 Coach Rosterbater is online and ready!");
    }
});

// Login
client.login(process.env.DISCORD_TOKEN);

