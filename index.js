require("dotenv").config();
const {
    ActionRowBuilder,
    ButtonBuilder,
    ButtonStyle,
    Client,
    EmbedBuilder,
    GatewayIntentBits,
    ModalBuilder,
    Partials,
    PermissionFlagsBits,
    SlashCommandBuilder,
    TextInputBuilder,
    TextInputStyle,
    time
} = require("discord.js");
const fs = require("fs");
const path = require("path");

const config = require("./config.json");

const STORAGE_PATH = path.join(__dirname, "storage.json");

const DEFAULT_DB = {
    games: [],
    stats: {
        players: {}
    }
};

const GAME_MODES = {
    "6s": {
        label: "6s",
        positions: [
            { key: "center", label: "Center", color: "Red", option: "center6" },
            { key: "leftWing", label: "Left Wing", color: "Green", option: "leftwing" },
            { key: "rightWing", label: "Right Wing", color: "Darker Blue", option: "rightwing" },
            { key: "leftDefense", label: "Left Defense", color: "Aqua/Teal", option: "leftdefense" },
            { key: "rightDefense", label: "Right Defense", color: "Yellow", option: "rightdefense" },
            { key: "goalie", label: "Goalie", color: "Purple", option: "goalie6" }
        ]
    },
    "4s": {
        label: "4s",
        positions: [
            { key: "center", label: "Center", color: "Red", option: "center4" },
            { key: "wing", label: "Wing", color: "Green", option: "wing" },
            { key: "defense", label: "Defense", color: "Aqua/Teal", option: "defense" },
            { key: "goalie", label: "Goalie", color: "Purple", option: "goalie4" }
        ]
    }
};

const REMINDER_SCHEDULE = [
    {
        key: "12h",
        offset: 12 * 60 * 60 * 1000,
        dm: (mention) => `Oi ${mention}! 12 hours out and you're ghosting me. Confirm that you're skating or I'll strap skates on a traffic cone instead.`,
        channel: (mention, label) => `${mention} — the ${label} slot is about to be deserted in 12 hours if our current player keeps hiding. Step up if you're ready.`
    },
    {
        key: "6h",
        offset: 6 * 60 * 60 * 1000,
        dm: (mention) => `${mention}, six hours to puck drop. If you don't smash that confirm button I'm mailing your gear to the thrift store.`,
        channel: (mention, label) => `${mention} still wide open six hours out. Someone with a spine grab the ${label} jersey.`
    },
    {
        key: "2h",
        offset: 2 * 60 * 60 * 1000,
        dm: (mention) => `${mention}! Two hours. That's 120 minutes of you ignoring me. Do I need to call your mom or are you finally confirming?`,
        channel: (mention, label) => `${mention} we're two hours from puck drop and this ${label} spot is still vapor. Hit the button if you're in.`
    },
    {
        key: "1h",
        offset: 60 * 60 * 1000,
        dm: (mention) => `${mention}, ONE hour. If you're not skating I'll dress the Zamboni driver. Confirm now or start running laps.`,
        channel: (mention, label) => `${mention} one hour warning. Coach is sharpening the bench for whoever wants this ${label} slot.`
    },
    {
        key: "30m",
        offset: 30 * 60 * 1000,
        dm: (mention) => `${mention}! Thirty minutes! At this point I'm questioning your life choices. Click confirm before I frame your jersey for \"Most Absent\".`,
        channel: (mention, label) => `${mention} last call with thirty minutes left. Claim the ${label} slot before we skate short.`
    }
];

const RESULT_DELAY_MS = 60 * 60 * 1000;

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.DirectMessages,
        GatewayIntentBits.GuildMembers
    ],
    partials: [Partials.Channel]
});

function loadDb() {
    try {
        if (!fs.existsSync(STORAGE_PATH)) {
            return JSON.parse(JSON.stringify(DEFAULT_DB));
        }

        const raw = fs.readFileSync(STORAGE_PATH, "utf8");
        if (!raw.trim()) {
            return JSON.parse(JSON.stringify(DEFAULT_DB));
        }

        const parsed = JSON.parse(raw);
        if (!parsed.games) parsed.games = [];
        if (!parsed.stats || !parsed.stats.players) {
            parsed.stats = { players: {} };
        }
        return parsed;
    } catch (error) {
        console.error("Failed to load storage.json", error);
        return JSON.parse(JSON.stringify(DEFAULT_DB));
    }
}

let db = loadDb();

function saveDb() {
    try {
        fs.writeFileSync(STORAGE_PATH, JSON.stringify(db, null, 2));
    } catch (error) {
        console.error("Failed to save storage.json", error);
    }
}

function ensurePlayerStats(userId) {
    if (!db.stats.players[userId]) {
        db.stats.players[userId] = {
            goals: 0,
            assists: 0,
            points: 0,
            shots: 0,
            saves: 0,
            gamesPlayed: 0,
            practices: 0,
            passingPercentageSum: 0,
            passingSamples: 0
        };
    }
    return db.stats.players[userId];
}

function getRoleMention(mode, key) {
    const roleId = config.roles?.[mode]?.[key];
    if (roleId) {
        return `<@&${roleId}>`;
    }
    const position = GAME_MODES[mode].positions.find((p) => p.key === key);
    return position ? `**${position.label}**` : "players";
}

function buildGameEmbed(game) {
    const mode = GAME_MODES[game.mode];
    const embed = new EmbedBuilder()
        .setTitle(`${game.type === "game" ? "League Game" : "Practice"} (${mode.label})`)
        .setDescription(`Scheduled for ${time(new Date(game.scheduledAt), "F")} (${time(new Date(game.scheduledAt), "R")})`)
        .setColor(game.type === "game" ? 0xff5555 : 0x55ff99)
        .setFooter({ text: `Game ID: ${game.id}` });

    if (game.opponent) {
        embed.addFields({ name: "Opponent", value: game.opponent, inline: false });
    }

    for (const position of mode.positions) {
        const slot = game.positions[position.key];
        let value = "*Open*";
        if (slot && slot.userId) {
            const status = game.type === "game" ? (slot.confirmed ? "✅ Confirmed" : "⏳ Pending") : "📝 Assigned";
            value = `<@${slot.userId}> — ${status}`;
        }
        embed.addFields({
            name: `${position.label} • ${position.color}`,
            value,
            inline: true
        });
    }

    if (game.status === "completed" && game.resultSummary) {
        embed.addFields({ name: "Result", value: game.resultSummary, inline: false });
    }

    return embed;
}

function getGameChannel(gameType) {
    if (gameType === "practice") {
        return config.channels?.practice ?? config.lineupChannelId;
    }
    return config.channels?.game ?? config.lineupChannelId;
}

async function postOpenSlotMessage(game, positionKey) {
    const mode = GAME_MODES[game.mode];
    const position = mode.positions.find((pos) => pos.key === positionKey);
    if (!position) return;

    const channelId = getGameChannel(game.type);
    if (!channelId) return;

    try {
        const channel = await client.channels.fetch(channelId);
        if (!channel) return;

        const row = new ActionRowBuilder().addComponents(
            new ButtonBuilder()
                .setCustomId(`volunteer|${game.id}|${position.key}`)
                .setLabel(`Volunteer for ${position.label}`)
                .setStyle(ButtonStyle.Primary)
        );

        const roleMention = getRoleMention(game.mode, position.key);
        const message = await channel.send({
            content: `${roleMention} — ${position.label} is open for the ${game.type === "game" ? "league game" : "practice"} **${game.id}**. Click below if you're available!`,
            components: [row]
        });

        if (!game.openSlotMessages) game.openSlotMessages = {};
        if (!game.openSlotMessages[position.key]) {
            game.openSlotMessages[position.key] = [];
        }
        game.openSlotMessages[position.key].push({ channelId: message.channelId, messageId: message.id });
        saveDb();
    } catch (error) {
        console.error("Failed to post open slot message", error);
    }
}

async function sendAssignmentDm(game, position, userId) {
    try {
        const user = await client.users.fetch(userId);
        if (!user) return;

        const base = `You're slotted as **${position.label} (${position.color})** for the ${game.type === "game" ? "league game" : "practice"} ${game.id} scheduled ${time(new Date(game.scheduledAt), "F")}.`;

        if (!game.positions[position.key].dmHistory) {
            game.positions[position.key].dmHistory = [];
        }

        if (game.type === "game") {
            const row = new ActionRowBuilder().addComponents(
                new ButtonBuilder()
                    .setCustomId(`confirm|${game.id}|${position.key}`)
                    .setLabel("I'm In")
                    .setStyle(ButtonStyle.Success),
                new ButtonBuilder()
                    .setCustomId(`decline|${game.id}|${position.key}`)
                    .setLabel("Can't Make It")
                    .setStyle(ButtonStyle.Danger)
            );

            const dmMessage = await user.send({
                content: `${base}\nPlease confirm so the team isn't left hanging.`,
                components: [row]
            });

            game.positions[position.key].dmHistory.push(dmMessage.id);
        } else {
            const dmMessage = await user.send({
                content: `${base}\nThis is a practice lobby — no confirmation needed, just show up ready to skate!`
            });
            game.positions[position.key].dmHistory.push(dmMessage.id);
        }
        saveDb();
    } catch (error) {
        console.error("Failed to DM assignment", error);
    }
}

async function remindPosition(game, position, reminder) {
    const slot = game.positions[position.key];
    if (!slot || !slot.userId || slot.confirmed) return;

    try {
        const user = await client.users.fetch(slot.userId);
        if (user) {
            await user.send({
                content: reminder.dm(`<@${slot.userId}>`),
                components: [
                    new ActionRowBuilder().addComponents(
                        new ButtonBuilder()
                            .setCustomId(`confirm|${game.id}|${position.key}`)
                            .setLabel("I'm In")
                            .setStyle(ButtonStyle.Success),
                        new ButtonBuilder()
                            .setCustomId(`decline|${game.id}|${position.key}`)
                            .setLabel("Can't Make It")
                            .setStyle(ButtonStyle.Danger)
                    )
                ]
            });
        }
    } catch (error) {
        console.error("Failed to DM reminder", error);
    }

    try {
        const channelId = getGameChannel(game.type);
        if (channelId) {
            const channel = await client.channels.fetch(channelId);
            if (channel) {
                await channel.send({
                    content: reminder.channel(getRoleMention(game.mode, position.key), position.label),
                    components: [
                        new ActionRowBuilder().addComponents(
                            new ButtonBuilder()
                                .setCustomId(`volunteer|${game.id}|${position.key}`)
                                .setLabel(`Volunteer for ${position.label}`)
                                .setStyle(ButtonStyle.Primary)
                        )
                    ]
                });
            }
        }
    } catch (error) {
        console.error("Failed to send channel reminder", error);
    }

    if (!slot.remindersSent) slot.remindersSent = [];
    slot.remindersSent.push(reminder.key);
    saveDb();
}

async function promptForStats(game) {
    if (game.statsPromptSent || game.status === "completed") return;

    try {
        const user = await client.users.fetch(game.createdBy);
        if (!user) return;

        const row = new ActionRowBuilder().addComponents(
            new ButtonBuilder()
                .setCustomId(`recordstats|${game.id}`)
                .setLabel("Enter Game Stats")
                .setStyle(ButtonStyle.Primary)
        );

        await user.send({
            content: `Great game, Coach! It's been an hour since **${game.id}** was scheduled to start. Hit the button to record the score, goals/assists (up to two assists), shots, passing percentage, and goalie saves. Use Discord mentions (e.g. @Skater) when entering player names.`,
            components: [row]
        });

        game.statsPromptSent = true;
        saveDb();
    } catch (error) {
        console.error("Failed to prompt for stats", error);
    }
}

async function updateGameMessage(game) {
    try {
        if (!game.channelId || !game.messageId) return;
        const channel = await client.channels.fetch(game.channelId);
        if (!channel) return;
        const message = await channel.messages.fetch(game.messageId);
        await message.edit({ embeds: [buildGameEmbed(game)] });
    } catch (error) {
        console.error("Failed to update game message", error);
    }
}

function parseSchedule(input) {
    const date = new Date(input);
    if (Number.isNaN(date.getTime())) {
        return null;
    }
    return date.toISOString();
}

function buildGameId(dateIso, mode) {
    return `${mode.toUpperCase()}-${dateIso}`;
}

function recordRosterAttendance(game) {
    const mode = GAME_MODES[game.mode];
    for (const position of mode.positions) {
        const slot = game.positions[position.key];
        if (slot?.userId) {
            const stats = ensurePlayerStats(slot.userId);
            if (game.type === "game") {
                stats.gamesPlayed += 1;
            } else {
                stats.practices += 1;
            }
        }
    }
}

function parseGoalLines(text) {
    if (!text) return [];
    return text
        .split(/\n+/)
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
            const parts = line.split(/[, ]+/).filter(Boolean);
            if (!parts.length) return null;
            const scorer = parts[0];
            const assists = parts.slice(1, 3);
            return { scorer, assists };
        })
        .filter(Boolean);
}

function parseValueLines(text) {
    if (!text) return [];
    return text
        .split(/\n+/)
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
            const match = line.match(/^(\S+)/);
            if (!match) return null;
            const idPart = match[1];
            const valueMatch = line.replace(idPart, "").match(/([0-9]+(?:\.[0-9]+)?)/);
            if (!valueMatch) return null;
            const value = Number(valueMatch[1]);
            if (Number.isNaN(value)) return null;
            return { id: idPart, value };
        })
        .filter(Boolean);
}

function extractUserId(raw) {
    const match = raw.match(/<@!?([0-9]+)>/);
    return match ? match[1] : null;
}

function applyStatsFromModal(game, data) {
    const goals = parseGoalLines(data.goals);
    const shots = parseValueLines(data.shots);
    const passes = parseValueLines(data.passing);
    const saves = parseValueLines(data.saves);

    const goalTextLines = [];

    for (const goal of goals) {
        const scorerId = extractUserId(goal.scorer);
        if (!scorerId) continue;
        const scorerStats = ensurePlayerStats(scorerId);
        scorerStats.goals += 1;
        scorerStats.points += 1;

        const assistMentions = [];
        for (const assist of goal.assists) {
            const assistId = extractUserId(assist);
            if (!assistId) continue;
            const assistStats = ensurePlayerStats(assistId);
            assistStats.assists += 1;
            assistStats.points += 1;
            assistMentions.push(`<@${assistId}>`);
        }
        goalTextLines.push(`${goal.scorer}${assistMentions.length ? ` (assists: ${assistMentions.join(", ")})` : ""}`);
    }

    for (const shot of shots) {
        const userId = extractUserId(shot.id);
        if (!userId) continue;
        const stats = ensurePlayerStats(userId);
        stats.shots += shot.value;
    }

    for (const pass of passes) {
        const userId = extractUserId(pass.id);
        if (!userId) continue;
        const stats = ensurePlayerStats(userId);
        stats.passingPercentageSum += pass.value;
        stats.passingSamples += 1;
    }

    for (const save of saves) {
        const userId = extractUserId(save.id);
        if (!userId) continue;
        const stats = ensurePlayerStats(userId);
        stats.saves += save.value;
    }

    const summaryLines = [`Score: ${data.score || "N/A"}`];
    if (goalTextLines.length) {
        summaryLines.push("Goals:");
        for (const line of goalTextLines) summaryLines.push(`• ${line}`);
    }
    if (shots.length) {
        summaryLines.push("Shots:");
        for (const shot of shots) summaryLines.push(`• ${shot.id}: ${shot.value}`);
    }
    if (passes.length) {
        summaryLines.push("Passing %:");
        for (const pass of passes) summaryLines.push(`• ${pass.id}: ${pass.value}%`);
    }
    if (saves.length) {
        summaryLines.push("Goalie Saves:");
        for (const save of saves) summaryLines.push(`• ${save.id}: ${save.value}`);
    }

    game.resultSummary = summaryLines.join("\n");
    game.status = "completed";
    saveDb();
}

function registerCommands() {
    const createGameCommand = new SlashCommandBuilder()
        .setName("create-game")
        .setDescription("Create a practice or league game lobby")
        .setDefaultMemberPermissions(PermissionFlagsBits.ManageEvents)
        .addStringOption((option) =>
            option
                .setName("type")
                .setDescription("Select practice or game")
                .setRequired(true)
                .addChoices(
                    { name: "Practice", value: "practice" },
                    { name: "League Game", value: "game" }
                )
        )
        .addStringOption((option) =>
            option
                .setName("mode")
                .setDescription("Choose between 4s or 6s format")
                .setRequired(true)
                .addChoices(
                    { name: "4s", value: "4s" },
                    { name: "6s", value: "6s" }
                )
        )
        .addStringOption((option) =>
            option
                .setName("scheduled")
                .setDescription("Start time in ISO format (e.g. 2024-05-01T21:30)")
                .setRequired(true)
        )
        .addStringOption((option) =>
            option
                .setName("opponent")
                .setDescription("Optional opponent name")
                .setRequired(false)
        )
        .addUserOption((option) => option.setName("center6").setDescription("6s Center").setRequired(false))
        .addUserOption((option) => option.setName("leftwing").setDescription("6s Left Wing").setRequired(false))
        .addUserOption((option) => option.setName("rightwing").setDescription("6s Right Wing").setRequired(false))
        .addUserOption((option) => option.setName("leftdefense").setDescription("6s Left Defense").setRequired(false))
        .addUserOption((option) => option.setName("rightdefense").setDescription("6s Right Defense").setRequired(false))
        .addUserOption((option) => option.setName("goalie6").setDescription("6s Goalie").setRequired(false))
        .addUserOption((option) => option.setName("center4").setDescription("4s Center").setRequired(false))
        .addUserOption((option) => option.setName("wing").setDescription("4s Wing").setRequired(false))
        .addUserOption((option) => option.setName("defense").setDescription("4s Defense").setRequired(false))
        .addUserOption((option) => option.setName("goalie4").setDescription("4s Goalie").setRequired(false));

    const leaderboardCommand = new SlashCommandBuilder()
        .setName("leaderboard")
        .setDescription("Show the current player stats table");

    const resetStatsCommand = new SlashCommandBuilder()
        .setName("reset-stats")
        .setDescription("Reset all stored player statistics")
        .setDefaultMemberPermissions(PermissionFlagsBits.Administrator);

    return [createGameCommand.toJSON(), leaderboardCommand.toJSON(), resetStatsCommand.toJSON()];
}

async function handleCreateGame(interaction) {
    const type = interaction.options.getString("type");
    const modeKey = interaction.options.getString("mode");
    const scheduledInput = interaction.options.getString("scheduled");
    const opponent = interaction.options.getString("opponent") || null;

    const scheduledIso = parseSchedule(scheduledInput);
    if (!scheduledIso) {
        return interaction.reply({ content: "I couldn't understand that date/time. Please provide it in ISO format, e.g. 2024-05-01T21:30", ephemeral: true });
    }

    const mode = GAME_MODES[modeKey];
    if (!mode) {
        return interaction.reply({ content: "Unsupported mode.", ephemeral: true });
    }

    const gameId = buildGameId(scheduledIso, modeKey);

    const positions = {};
    for (const position of mode.positions) {
        const user = interaction.options.getUser(position.option);
        positions[position.key] = {
            userId: user ? user.id : null,
            confirmed: type === "practice",
            remindersSent: [],
            dmHistory: []
        };
    }

    const game = {
        id: gameId,
        type,
        mode: modeKey,
        scheduledAt: scheduledIso,
        opponent,
        createdBy: interaction.user.id,
        createdAt: new Date().toISOString(),
        positions,
        status: "scheduled"
    };

    const channelId = getGameChannel(type);
    if (!channelId) {
        return interaction.reply({ content: "No target channel configured for this type of lobby. Please update config.json.", ephemeral: true });
    }

    try {
        const channel = await client.channels.fetch(channelId);
        if (!channel) {
            return interaction.reply({ content: "I couldn't access the configured channel.", ephemeral: true });
        }

        const message = await channel.send({ embeds: [buildGameEmbed(game)] });
        game.channelId = message.channelId;
        game.messageId = message.id;

        db.games.push(game);
        saveDb();

        await interaction.reply({ content: `Created ${type === "game" ? "league game" : "practice"} ${gameId} in <#${channelId}>.`, ephemeral: true });

        for (const position of mode.positions) {
            const slot = positions[position.key];
            if (slot.userId) {
                await sendAssignmentDm(game, position, slot.userId);
            } else {
                await postOpenSlotMessage(game, position.key);
            }
        }

        saveDb();
        await updateGameMessage(game);
    } catch (error) {
        console.error("Failed to create game", error);
        return interaction.reply({ content: "Something went wrong while creating the lobby.", ephemeral: true });
    }
}

function aggregateLeaderboard() {
    const entries = Object.entries(db.stats.players).map(([userId, stats]) => ({ userId, ...stats }));
    entries.sort((a, b) => b.points - a.points || b.goals - a.goals || b.assists - a.assists);
    return entries.slice(0, 25);
}

async function handleLeaderboard(interaction) {
    const leaderboard = aggregateLeaderboard();
    if (!leaderboard.length) {
        return interaction.reply({ content: "No stats recorded yet. Get some games on the books!", ephemeral: true });
    }

    const lines = leaderboard.map((entry, index) => {
        const passingAverage = entry.passingSamples ? (entry.passingPercentageSum / entry.passingSamples).toFixed(1) : "--";
        return `**${index + 1}.** <@${entry.userId}> — ${entry.points} pts (${entry.goals}G/${entry.assists}A) | Shots: ${entry.shots} | Saves: ${entry.saves} | Passing: ${passingAverage}% | Games: ${entry.gamesPlayed} | Practices: ${entry.practices}`;
    });

    const embed = new EmbedBuilder()
        .setTitle("Coach's Leaderboard")
        .setColor(0x3498db)
        .setDescription(lines.join("\n"));

    return interaction.reply({ embeds: [embed] });
}

async function handleResetStats(interaction) {
    if (!interaction.memberPermissions?.has(PermissionFlagsBits.Administrator)) {
        return interaction.reply({ content: "Only an administrator can reset the stats.", ephemeral: true });
    }

    db.stats = { players: {} };
    saveDb();
    return interaction.reply({ content: "All player stats have been reset.", ephemeral: true });
}

async function handleVolunteer(interaction, gameId, positionKey) {
    const game = db.games.find((g) => g.id === gameId);
    if (!game) {
        return interaction.reply({ content: "That game is no longer available.", ephemeral: true });
    }

    const mode = GAME_MODES[game.mode];
    if (!mode) {
        return interaction.reply({ content: "Invalid game configuration.", ephemeral: true });
    }

    const position = mode.positions.find((pos) => pos.key === positionKey);
    if (!position) {
        return interaction.reply({ content: "That position isn't part of this lobby.", ephemeral: true });
    }

    if (!game.volunteers) game.volunteers = {};
    if (!game.volunteers[positionKey]) game.volunteers[positionKey] = [];

    if (!game.volunteers[positionKey].includes(interaction.user.id)) {
        game.volunteers[positionKey].push(interaction.user.id);
        saveDb();
    }

    try {
        const creator = await client.users.fetch(game.createdBy);
        if (creator) {
            await creator.send(`**${interaction.user.tag}** volunteered for **${position.label}** in ${game.id}. Connect with them if you need a replacement.`);
        }
    } catch (error) {
        console.error("Failed to notify creator about volunteer", error);
    }

    return interaction.reply({ content: `Thanks for stepping up! The lobby creator has been notified that you're available for ${position.label}.`, ephemeral: true });
}

async function handleConfirm(interaction, gameId, positionKey, confirmed) {
    const game = db.games.find((g) => g.id === gameId);
    if (!game) {
        return interaction.reply({ content: "That game doesn't exist anymore.", ephemeral: true });
    }

    const slot = game.positions[positionKey];
    if (!slot || !slot.userId) {
        return interaction.reply({ content: "This position isn't assigned right now.", ephemeral: true });
    }

    if (slot.userId !== interaction.user.id) {
        return interaction.reply({ content: "You're not assigned to this position.", ephemeral: true });
    }

    if (confirmed) {
        slot.confirmed = true;
        saveDb();
        await updateGameMessage(game);
        return interaction.reply({ content: "Confirmed! Coach knows you're skating.", ephemeral: true });
    }

    slot.userId = null;
    slot.confirmed = false;
    slot.remindersSent = [];
    saveDb();
    await updateGameMessage(game);
    await postOpenSlotMessage(game, positionKey);
    return interaction.reply({ content: "Understood. We'll find someone else to fill the spot.", ephemeral: true });
}

async function handleStatsModal(interaction, gameId) {
    const game = db.games.find((g) => g.id === gameId);
    if (!game) {
        return interaction.reply({ content: "Couldn't find that game anymore.", ephemeral: true });
    }

    if (interaction.user.id !== game.createdBy) {
        return interaction.reply({ content: "Only the lobby creator can submit stats for this game.", ephemeral: true });
    }

    recordRosterAttendance(game);
    applyStatsFromModal(game, {
        score: interaction.fields.getTextInputValue("score"),
        goals: interaction.fields.getTextInputValue("goals"),
        shots: interaction.fields.getTextInputValue("shots"),
        passing: interaction.fields.getTextInputValue("passing"),
        saves: interaction.fields.getTextInputValue("saves")
    });

    await updateGameMessage(game);
    saveDb();

    return interaction.reply({ content: "Stats recorded! Leaderboards updated.", ephemeral: true });
}

client.once("ready", async () => {
    console.log(`✅ Logged in as ${client.user.tag}`);
    try {
        const commands = registerCommands();
        await client.application.commands.set(commands);
        console.log("Slash commands registered.");
    } catch (error) {
        console.error("Failed to register slash commands", error);
    }

    setInterval(async () => {
        const now = Date.now();
        for (const game of db.games) {
            if (!GAME_MODES[game.mode]) continue;

            const scheduledTime = new Date(game.scheduledAt).getTime();
            if (Number.isNaN(scheduledTime)) continue;

            if (game.type === "game") {
                if (now >= scheduledTime + RESULT_DELAY_MS) {
                    await promptForStats(game);
                }

                for (const position of GAME_MODES[game.mode].positions) {
                    const slot = game.positions[position.key];
                    if (!slot || !slot.userId || slot.confirmed) continue;

                    for (const reminder of REMINDER_SCHEDULE) {
                        if (slot.remindersSent?.includes(reminder.key)) continue;
                        if (scheduledTime - now <= reminder.offset) {
                            await remindPosition(game, position, reminder);
                            break;
                        }
                    }
                }
            }
        }
    }, 60 * 1000);
});

client.on("interactionCreate", async (interaction) => {
    if (interaction.isChatInputCommand()) {
        if (interaction.commandName === "create-game") {
            return handleCreateGame(interaction);
        }
        if (interaction.commandName === "leaderboard") {
            return handleLeaderboard(interaction);
        }
        if (interaction.commandName === "reset-stats") {
            return handleResetStats(interaction);
        }
    }

    if (interaction.isButton()) {
        const [action, gameId, positionKey] = interaction.customId.split("|");
        if (action === "volunteer") {
            return handleVolunteer(interaction, gameId, positionKey);
        }
        if (action === "confirm") {
            return handleConfirm(interaction, gameId, positionKey, true);
        }
        if (action === "decline") {
            return handleConfirm(interaction, gameId, positionKey, false);
        }
        if (action === "recordstats") {
            const game = db.games.find((g) => g.id === gameId);
            if (!game) {
                return interaction.reply({ content: "I can't find that game anymore.", ephemeral: true });
            }
            if (interaction.user.id !== game.createdBy) {
                return interaction.reply({ content: "Only the lobby creator can record stats.", ephemeral: true });
            }

            const modal = new ModalBuilder()
                .setCustomId(`statsmodal|${gameId}`)
                .setTitle("Record Game Stats");

            modal.addComponents(
                new ActionRowBuilder().addComponents(
                    new TextInputBuilder()
                        .setCustomId("score")
                        .setLabel("Final Score (e.g. 4-2 vs Rival)")
                        .setStyle(TextInputStyle.Short)
                        .setRequired(true)
                ),
                new ActionRowBuilder().addComponents(
                    new TextInputBuilder()
                        .setCustomId("goals")
                        .setLabel("Goals (one per line: @Scorer @Assist1 @Assist2)")
                        .setStyle(TextInputStyle.Paragraph)
                        .setRequired(false)
                ),
                new ActionRowBuilder().addComponents(
                    new TextInputBuilder()
                        .setCustomId("shots")
                        .setLabel("Shots (e.g. @Player 5)")
                        .setStyle(TextInputStyle.Paragraph)
                        .setRequired(false)
                ),
                new ActionRowBuilder().addComponents(
                    new TextInputBuilder()
                        .setCustomId("passing")
                        .setLabel("Passing % (e.g. @Player 78.5)")
                        .setStyle(TextInputStyle.Paragraph)
                        .setRequired(false)
                ),
                new ActionRowBuilder().addComponents(
                    new TextInputBuilder()
                        .setCustomId("saves")
                        .setLabel("Goalie Saves (e.g. @Goalie 22)")
                        .setStyle(TextInputStyle.Paragraph)
                        .setRequired(false)
                )
            );

            return interaction.showModal(modal);
        }
    }

    if (interaction.isModalSubmit()) {
        const [action, gameId] = interaction.customId.split("|");
        if (action === "statsmodal") {
            return handleStatsModal(interaction, gameId);
        }
    }
});

client.login(process.env.DISCORD_TOKEN);
