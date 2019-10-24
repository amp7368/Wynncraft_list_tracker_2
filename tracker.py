import gc
import time
import discord
import asyncio
from aiohttp import client_exceptions
import urllib.request
import urllib.error
import traceback
from json import dumps
from json import loads
import datetime

client = discord.Client(max_messages=1000)
bot_user = ['bot_user']
begun = [False]
prefix = "at!"
entries_per_page = 18
# {"territories": territories, "guild_count": guild count}
territory_cache = dict()

# {client id: {list_name: {"guild": [guild name, guild name...], "territories":[terr,terr,...terr], "guild": [guild name, guild name...], "territories":[terr,terr,...terr],... "guild": [guild name, guild name...], "territories":{...}},client id:[...],...}
lists = dict()
# {client id: {list_name:{"message":message,"page":page,"reactions":bool},list_name:{"message":message,"page":page}...], client id: [...]}
charts = dict()
# {client id: {list_name:{"message":message,"page":page,"reactions":bool},list_name:{"message":message}...], client id: [...]}
missings = dict()
# {client id: {list_name:{"channel":channel},list_name:{"channel":channel,"page":page}...], client id: [...]}
exchanges = dict()
# {client id: {list_name:{"channel":channel,"role": role,"threshold":threshold,"safe":bool},list_name:{"channel":channel,"threshold":threshold,"safe":bool}...], client id: [...]}
alerts = dict()

with open('config.txt') as config:
    p = 0
    for line in config:
        line = line.split("#")[0].strip()
        if p == 0:
            line = line.split(",")
            color = discord.colour.Color.from_rgb(int(line[0]), int(line[1]), int(line[2]))
        elif p == 1:
            AppleBot = line
        elif p == 2:
            test_AppleBot = line
        elif p == 3:
            login = line
        elif p == 4:
            test_login = line
        elif p == 5:
            begin_channel = int(line)
        elif p == 6:
            debug_person = line
        elif p == 7:
            respects = int(line)
        else:
            break
        p += 1


@client.event
async def on_ready():
    try:
        await client.get_channel(begin_channel).send(prefix + "begin")
    except:
        await asyncio.sleep(5)


@client.event
async def on_reaction_add(reaction, user):
    if reaction.count == 1 or reaction.emoji not in ("➡", "⬅"):
        return
    if reaction.emoji == "➡":
        left = False
    else:
        left = True
    for cl in missings:
        for list_name in list(missings[cl].keys()):
            if missings[cl][list_name]['message'].id == reaction.message.id:
                info = missings[cl][list_name]
                await info['message'].remove_reaction(reaction, user)
                if left:
                    info['page'] = max(info['page'] - 1, 0)
                else:
                    info['page'] += 1
                await collect_missings(cl, list_name, territory_cache['territories'])
                return
    for cl in charts:
        for list_name in list(charts[cl].keys()):
            if charts[cl][list_name]['message'].id == reaction.message.id:
                info = charts[cl][list_name]
                await info['message'].remove_reaction(reaction, user)
                if left:
                    info['page'] = max(info['page'] - 1, 0)
                else:
                    info['page'] += 1
                await collect_chart(cl, list_name, territory_cache['territories'])
                return


@client.event
async def on_message(message):
    if not message.content.startswith(prefix):
        return

    content = message.content[len(prefix):].split(" ")[0]

    if content == "begin" and str(message.author.id) == AppleBot and not begun[0]:
        await begin()
    if content == "end" and str(message.author.id) == debug_person:
        await end(message)

    if message.author.bot:
        return
    if str(message.author.id) not in lists:
        new_client(str(message.author.id))
    if content in commands_set:
        await commands_set[content](message)


async def begin():
    await client.get_channel(begin_channel).send("begun")
    begun[0] = True
    await read()
    terrs_past = (await get_terr_list())['territories']
    territory_cache['territories'] = terrs_past

    count = 0

    while begun[0]:
        start_time = time.time()
        # do stuff
        try:
            terrs_past = await inner_begin(terrs_past)
        except:
            await send_trace()

        gc.collect()
        await asyncio.sleep(int(max(5, int(30 - (time.time() - start_time)))))
        if count == 20:
            count = 0
            await resend_messages()
        else:
            count += 1


async def inner_begin(terrs_past):
    terrs_now = (await get_terr_list())['territories']
    guild_terrs = dict()
    for terr_name in terrs_now:
        guild_name = terrs_now[terr_name]['guild']
        if guild_name in guild_terrs:
            guild_terrs[guild_name] += 1
        else:
            guild_terrs[guild_name] = 1
    territory_cache['guild_count'] = guild_terrs
    for client_id in charts:
        for list_name in list(charts[client_id].keys()):
            await collect_chart(client_id, list_name, terrs_now)
    for client_id in missings:
        for list_name in list(missings[client_id].keys()):
            await collect_missings(client_id, list_name, terrs_now)
    for client_id in alerts:
        for list_name in list(alerts[client_id].keys()):
            await collect_alerts(client_id, list_name, terrs_now)
    for client_id in exchanges:
        for list_name in list(exchanges[client_id].keys()):
            await collect_exchanges(client_id, list_name, terrs_now, terrs_past, guild_terrs)
    return terrs_now


async def resend_messages():
    for client_id in list(missings.keys()):
        for list_name in list(missings[client_id].keys()):
            content = missings[client_id][list_name]['message'].content
            channel = missings[client_id][list_name]['message'].channel
            try:
                await channel.delete_messages([missings[client_id][list_name]['message']])
                missings[client_id][list_name]['message'] = await channel.send(content)
                if missings[client_id][list_name]['reactions']:
                    await add_reactions(missings[client_id][list_name])
            except (discord.errors.NotFound, discord.errors.Forbidden):
                try:
                    missings.__delitem__(list_name)
                except KeyError:
                    # already gone
                    pass
                write()
                continue
            except:
                pass

    for client_id in list(charts.keys()):
        for list_name in list(charts[client_id].keys()):
            content = charts[client_id][list_name]['message'].content
            channel = charts[client_id][list_name]['message'].channel
            try:
                await channel.delete_messages([charts[client_id][list_name]['message']])
                charts[client_id][list_name]['message'] = await channel.send(content)
                if charts[client_id][list_name]['reactions']:
                    await add_reactions(charts[client_id][list_name])
            except (discord.errors.NotFound, discord.errors.Forbidden):
                try:
                    missings.__delitem__(list_name)
                except KeyError:
                    # already gone
                    pass
                write()
                continue
            except:
                pass


async def end(message):
    write()
    for client_id in missings:
        for list_name in list(missings[client_id].keys()):
            try:
                await missings[client_id][list_name]['message'].channel.delete_messages(
                    [missings[client_id][list_name]['message']])
            except (discord.errors.NotFound, discord.errors.Forbidden):
                pass
    for client_id in charts:
        for list_name in list(charts[client_id].keys()):
            try:
                await charts[client_id][list_name]['message'].channel.delete_messages(
                    [charts[client_id][list_name]['message']])
            except (discord.errors.NotFound, discord.errors.Forbidden):
                pass
    begun[0] = False
    await message.channel.send("ended")


async def collect_chart(client_id, list_name, terrs_now):
    lst = list()
    for terr in lists[client_id][list_name]['territories']:
        if terr in terrs_now:
            lst.append(terrs_now[terr])
        else:
            lists[client_id][list_name]['territories'].remove(terr)
    while len(lst) < charts[client_id][list_name]["page"] * entries_per_page:
        charts[client_id][list_name]["page"] -= 1
    lst_final = lst[charts[client_id][list_name]["page"] * entries_per_page:charts[client_id][list_name][
                                                                                "page"] * entries_per_page + entries_per_page]
    try:
        await charts[client_id][list_name]["message"].edit(
            content=make_chart(lst_final, entries_per_page * charts[client_id][list_name]["page"], len(lst)))
    except (discord.errors.NotFound, discord.errors.Forbidden):
        try:
            charts.__delitem__(list_name)
        except KeyError:
            # already gone
            pass
        write()
        return
    # add reactions
    if len(lst) > entries_per_page:
        if not charts[client_id][list_name]['reactions']:
            await add_reactions(charts[client_id][list_name])
    else:
        if charts[client_id][list_name]['reactions']:
            await remove_reactions(charts[client_id][list_name])
        charts[client_id][list_name]['reactions'] = False


def make_chart(lst, at_number, total_number):
    string_message = '```ml\n'
    string_message += '|   ' + "{:<35}".format(
        "Territories (" + str(total_number) + ")") + '|  ' + "{:<23}".format(
        "Owner") + '|  ' + "{:<23}".format(
        "Time Owned") + '|' + '\n'
    string_message += ('+----' + '-' * 34 + '+' + '-' * 25 + '+' + '-' * 25 + '+\n')
    count = at_number + 1
    for terr in lst:
        string_message += "{:<3}".format(str(count) + '.') + " " + "{:<35}".format(terr["territory"]) + '|'
        string_message += '  ' + "{:<23}".format(terr['guild']) + '|'
        string_message += '  ' + "{:<23}".format(time_subtract(terr['acquired'], time.time())) + '|'
        string_message += '\n'
        count += 1
    string_message += ('-' * 39 + '+' + '-' * 25 + '+' + '-' * 25 + '+\n')
    string_message += '```'
    if len(string_message) > 1999:
        string_message = string_message[:1975] + "\n```Message too long"
    return string_message


async def collect_missings(client_id, list_name, terrs_now):
    missing = list()
    for terr_name in lists[client_id][list_name]['territories']:
        if terr_name in terrs_now:
            if terrs_now[terr_name]['guild'] not in lists[client_id][list_name]['guild']:
                missing.append(terrs_now[terr_name])
        else:
            lists[client_id][list_name]['territories'].remove(terr_name)

    while len(missing) < missings[client_id][list_name]['page'] * entries_per_page:
        missings[client_id][list_name]["page"] -= 1
    lst_final = missing[missings[client_id][list_name]["page"] * entries_per_page:missings[client_id][list_name][
                                                                                      "page"] * entries_per_page + entries_per_page]
    try:
        await missings[client_id][list_name]["message"].edit(
            content=make_missing(lst_final, missings[client_id][list_name]['page'] * entries_per_page, len(missing)))
    except (discord.errors.NotFound, discord.errors.Forbidden):
        try:
            charts.__delitem__(list_name)
        except KeyError:
            # already gone
            pass
        write()
        return

    # add reactions
    if len(missing) > entries_per_page:
        if not missings[client_id][list_name]['reactions']:
            await add_reactions(missings[client_id][list_name])
    else:
        missings[client_id][list_name]['reactions'] = False
    return len(missing)


def make_missing(lst, at_number, total_number):
    if total_number == 0:
        return "No territories missing ^-^\n :white_check_mark:"
    string_message = '```ml\n'
    string_message += '|   ' + "{:<35}".format(
        "Territories Missing (" + str(total_number) + ")") + '|  ' + "{:<23}".format(
        "Owner") + '|  ' + "{:<23}".format("Time Owned") + '|' + '\n'
    string_message += ('+----' + '-' * 34 + '+' + '-' * 25 + '+' + '-' * 25 + '+\n')
    count = at_number + 1
    for terr in lst:
        string_message += "{:<3}".format(str(count) + '.') + " " + "{:<35}".format(terr['territory']) + '|'
        string_message += '  ' + "{:<23}".format(terr['guild']) + '|'
        string_message += '  ' + "{:<23}".format(time_subtract(terr['acquired'], time.time())) + '|'
        string_message += '\n'
        count += 1
    string_message += ('-' * 39 + '+' + '-' * 25 + '+' + '-' * 25 + '+\n')
    string_message += '```'
    if len(string_message) > 1999:
        string_message = string_message[:1975] + "\n```Message too long"
    return string_message


async def collect_alerts(client_id, list_name, terrs_now):
    num_missing = 0
    for terr_name in lists[client_id][list_name]['territories']:
        if terr_name in terrs_now:
            if terrs_now[terr_name]['guild'] not in lists[client_id][list_name]['guild']:
                num_missing += 1
        else:
            lists[client_id][list_name]['territories'].remove(terr_name)

    if alerts[client_id][list_name]["safe"]:
        if num_missing > alerts[client_id][list_name]["threshold"]:
            alerts[client_id][list_name]["safe"] = False
            try:
                await alerts[client_id][list_name]["channel"].send(
                    alerts[client_id][list_name]['role'][1:] + " you're not safe in " + list_name + "!")
            except:
                pass
    else:
        if num_missing == 0 or num_missing < alerts[client_id][list_name]["threshold"] * .7:
            alerts[client_id][list_name]["safe"] = True


async def collect_exchanges(client_id, list_name, terrs_now, terrs_past, guild_terrs):
    for terr_name in lists[client_id][list_name]['territories']:
        owner_now = terrs_now[terr_name]['guild']
        owner_past = terrs_past[terr_name]['guild']
        if owner_now != owner_past:
            if owner_now in lists[client_id][list_name]['guild']:
                if owner_past in lists[client_id][list_name]['guild']:
                    tempcolor = discord.Colour.blue()
                else:
                    tempcolor = discord.Colour.green()
            else:
                if owner_past in lists[client_id][list_name]['guild']:
                    tempcolor = discord.Colour.red()
                else:
                    tempcolor = discord.Colour.orange()

            if owner_past in guild_terrs:
                count1 = guild_terrs[owner_past]
            else:
                count1 = 0
            if owner_now in guild_terrs:
                count2 = guild_terrs[owner_now]
            else:
                count2 = 0
            try:
                await exchanges[client_id][list_name]["channel"].send(
                    embed=discord.Embed(color=tempcolor, description=owner_past + " (" + str(
                        count1) + ") --> **" + owner_now + "** (" + str(count2) + ")"))
            except:
                pass


async def on_command_write(message):
    write()
    await message.channel.send("wrote")


async def on_command_show(message):
    string = 'charts: ' + ', '.join(charts[str(message.author.id)])
    string += '\nmissings: ' + ', '.join(missings[str(message.author.id)])
    string += '\nexchanges: ' + ', '.join(exchanges[str(message.author.id)])
    string += '\nalerts: ' + ', '.join(alerts[str(message.author.id)])
    if string != '':
        try:
            while string != '':
                await message.channel.send(string[:1890])
                string = string[1890:]
        except:
            pass


async def on_command_show_lists(message):
    if len(lists[str(message.author.id)]) == 0:
        try:
            await message.channel.send("No lists to show")
        except:
            pass
        return
    for list_name in list(lists[str(message.author.id)].keys()):
        string = "**" + list_name + "**\n"
        string += "*" + '\n'.join(lists[str(message.author.id)][list_name]['guild']) + "*"
        string += "\n\n"
        string += '\n'.join(lists[str(message.author.id)][list_name]['territories'])
        if string != '':
            try:
                while string != '':
                    await message.channel.send(string[:1890])
                    string = string[1890:]
            except:
                pass


async def on_command_help(message):
    '''
    sends a list of commands to the user in the current channel
    :param message: the message the user just sent
    :return:
    '''
    try:
        await message.channel.send(embed=discord.Embed(
            color=color,
            description='**' + prefix + 'help** - Shows a list of commands\n' +
                        '**' + prefix + 'info** - Shows basic information on AppleBot\n' +
                        '**' + prefix + 'instructions** - Gives some instructions for how to use the bot\n'
                                        '\n' +
                        '**' + prefix + 'list create <list name> <rightful owner>** - Creates an empty list\n' +
                        '**' + prefix + 'list all <list name> ** - Creates a list of all territories\n' +
                        '**' + prefix + 'list copyterritories <list name> <guild name>** - Creates a list and adds all territories owned by a guild to the list\n' +
                        '**' + prefix + 'list (add/remove) (guilds/territories) <list name> (guilds/territories)** - Adds/removes a guild(s)/territory(s) to/from a list\n' +
                        '\n' +
                        '**' + prefix + 'start chart <list name>** - Creates an updating table that shows territories on a list and what guild owns them\n' +
                        '**' + prefix + 'start missing <list name>** - Creates an updating table that shows territories that are not owned by the guild that owns the list\n' +
                        '**' + prefix + 'start territories <list name>** - Creates a continuous feed of war activity in territories on a list\n' +
                        '**' + prefix + 'start alert <list name> <\\ \\@role name> <threshold #>** - Pings a specific role when a territory from a list has been taken from the guild that owns said list\n' +
                        'threshold # is the amount of territories you\'re allowed to lose before being pinged\n' +
                        '\n' +
                        '**' + prefix + 'show_lists** - shows your lists\n' +
                        '**' + prefix + 'show** - shows the active feeds you have\n' +

                        '\n' +
                        '**' + prefix + 'remove (charts/missings/territories/alerts) <list name>** - removes the feed from the list name (use this instead of deleting the message)\n'

        ))
    except:
        pass


async def on_command_info(message):
    '''
    sends some info about the bot to the user in the current channel
    :param message: the message the user just sent
    :return:
    '''
    try:
        await message.channel.send(embed=discord.Embed(
            color=color, description="__**AppleBot:**__\n" +
                                     "**Author:** appleptr16#5054\n" +
                                     "**AppleBot's discord:** https://discord.gg/XEyUWu9\n" +
                                     "Some commands are inspired by moto-bot\n" +
                                     "Another bot that I found out about after I finished AppleBot\n" +
                                     "**Release version:** 2.0\n" +
                                     "**Testing status:** Alpha (expect bugs)\n" +
                                     "**Server count:** " + str(len(client.guilds)) + '\n' +
                                     "**bot invite below**\n" +
                                     "https://bit.ly/31liFdF"))
    except:
        pass


async def on_command_instructions(message):
    '''
    send an instructions message to the location of message
    :param message: the message that requested this message
    :return:
    '''
    try:
        await message.channel.send("```Each individual has their own set of lists\n\n" +
                                   "1. Create a list with the !list command\n" +
                                   "    + Make an empty list\n" +
                                   "        - !list create <list name> <rightful owner>\n" +
                                   "        - !list (add/remove) <list name> <territory name>\n" +
                                   "    + Make a list from existing ownership of an area\n" +
                                   "        - !list copyterritories <list name> <guild name>\n" +
                                   "        - !list (add/remove) <list name> <territory name>\n" +
                                   "\n" +
                                   "2. Start a feature with the !start command\n" +
                                   "    + Make a single message chart that will update as time goes on\n" +
                                   "        - !start chart <list name>\n" +
                                   "        - !start missing <list name>\n" +
                                   "    + Make a territory exchanges feed for the list\n" +
                                   "        - !start territories <list name>\n" +
                                   "    + Make a mention whenever the list loses a defined number of territories\n" +
                                   "        - !start alert <list name> \@<role name> <threshold (number)>\n" +
                                   "3. Remove a feed (removing the message doesn't work\n" +
                                   "    + !remove (chart/missing/territories/alert/full_missing) <list name>\n```")

    except:
        pass


async def on_command_print_terrs(message):
    terrs = ', '.join(territory_cache['territories'])
    while terrs != '':
        try:
            await message.channel.send(terrs[:1890])
        except:
            pass
        terrs = terrs[1890:]


async def on_command_list(message):
    msgs = message.content.split(' ')
    if len(msgs) < 2:
        await correct_command_list(message.channel)
        return
    if msgs[1] == "create":
        await on_command_list_create(message)
    elif msgs[1] == "copyterritories":
        await on_command_list_copyterritories(message)
    elif msgs[1] == "all":
        await on_command_list_all(message)
    elif msgs[1] == "add":
        await on_command_list_add(message)
    elif msgs[1] == "remove":
        await on_command_list_remove(message)
    else:
        await correct_command_list(message.channel)
    write()


async def on_command_list_all(message):
    msgs = message.content.split(" ")
    if len(msgs) != 3:
        await correct_command_list_all(message.channel)
        return
    list_name = msgs[2]
    owners = []
    territories = list()
    for i in territory_cache['territories']:
        territories.append(i)
    lists[str(message.author.id)][list_name] = {"guild": owners, 'territories': territories}
    try:
        await message.channel.send(list_name + " was created")
    except:
        pass


async def on_command_list_create(message):
    msgs = message.content.split(" ")
    if len(msgs) < 4:
        await correct_command_list_create(message.channel)
        return
    list_name = msgs[2]
    owners = ' '.join(msgs[3:]).split(',')
    lists[str(message.author.id)][list_name] = {"guild": owners, "territories": list()}
    try:
        await message.channel.send(list_name + " was created")
    except:
        pass
    # TODO DONT ALLOW KEY WORDS CHART MISSING TERRITORIES ALERT FULL_MISSING


async def on_command_list_copyterritories(message):
    msgs = message.content.split(" ")
    if len(msgs) < 4:
        await correct_command_list_copyterritories(message.channel)
        return
    list_name = msgs[2]
    owner = ' '.join(msgs[3:]).strip()
    if owner not in territory_cache['guild_count']:
        try:
            await message.channel.send(owner + " is not a guild or has no territories")
        except:
            pass
        return
    terrs = list()
    for terr_name in territory_cache['territories']:
        if territory_cache['territories'][terr_name]['guild'] == owner:
            terrs.append(terr_name)

    lists[str(message.author.id)][list_name] = {"guild": [owner], 'territories': terrs}
    string = "**" + list_name + "**\n"
    string += "*" + '\n'.join(lists[str(message.author.id)][list_name]['guild']) + "*"
    string += "\n\n"
    string += '\n'.join(lists[str(message.author.id)][list_name]['territories'])
    if string != '':
        try:
            while string != '':
                await message.channel.send(string[:1890])
                string = string[1890:]
        except:
            pass


async def on_command_list_add(message):
    msgs = message.content.split(" ")
    if len(msgs) < 3:
        await correct_command_list_add(message.channel)
        return
    if msgs[2] == "guilds":
        await on_command_list_add_guilds(message)
    elif msgs[2] == "territories":
        await on_command_list_add_territories(message)
    else:
        await correct_command_list_add(message.channel)
        return


async def on_command_list_add_guilds(message):
    msgs = message.content.split(" ")
    if len(msgs) < 5:
        await correct_command_list_add_guild(message.channel)
        return
    list_name = msgs[3]
    if list_name not in lists[str(message.author.id)]:
        await is_not_a_list(list_name, message.channel)
        return
    guilds = ' '.join(msgs[4:]).split(',')
    for guild_name in guilds:
        lists[str(message.author.id)][list_name]['guild'].append(guild_name.strip())
        try:
            await message.channel.send(guild_name.strip() + " added")
        except:
            pass


async def on_command_list_add_territories(message):
    msgs = message.content.split(" ")
    if len(msgs) < 5:
        await correct_command_list_add_territories(message.channel)
        return
    list_name = msgs[3]
    if list_name not in lists[str(message.author.id)]:
        await is_not_a_list(list_name, message.channel)
        return
    territories = ' '.join(msgs[4:]).split(',')
    for territory_name in territories:
        if territory_name.strip() in territory_cache['territories']:
            lists[str(message.author.id)][list_name]['territories'].append(territory_name.strip())
            try:
                await message.channel.send(territory_name.strip() + " added")
            except:
                pass
        else:
            try:
                await message.channel.send(territory_name.strip() + " not added")
            except:
                pass


async def on_command_list_remove(message):
    msgs = message.content.split(" ")
    if len(msgs) < 3:
        await correct_command_remove(message.channel)
        return
    if msgs[2] == "guilds":
        await on_command_list_remove_guilds(message)
    elif msgs[2] == "territories":
        await on_command_list_remove_territories(message)
    else:
        await correct_command_list_remove(message.channel)
        return


async def on_command_list_remove_guilds(message):
    msgs = message.content.split(" ")
    if len(msgs) < 5:
        await correct_command_list_remove_guild(message.channel)
        return
    list_name = msgs[3]
    if list_name not in lists[str(message.author.id)]:
        await is_not_a_list(list_name, message.channel)
        return
    guilds = ' '.join(msgs[4:]).split(',')
    for guild_name in guilds:
        if guild_name.strip() in lists[str(message.author.id)][list_name]['guild']:
            lists[str(message.author.id)][list_name]['guild'].remove(guild_name.strip())
            try:
                await message.channel.send(guild_name.strip() + " removed")
            except:
                pass
        else:
            try:
                await message.channel.send(guild_name + " is not a guild in the list")
            except:
                pass


async def on_command_list_remove_territories(message):
    msgs = message.content.split(" ")
    if len(msgs) < 5:
        await correct_command_list_remove_territories(message.channel)
        return
    list_name = msgs[3]
    if list_name not in lists[str(message.author.id)]:
        await is_not_a_list(list_name, message.channel)
        return
    territories = ' '.join(msgs[4:]).split(',')
    for territory_name in territories:
        if territory_name.strip() in lists[str(message.author.id)][list_name]['territories']:
            lists[str(message.author.id)][list_name]['territories'].remove(territory_name.strip())
            try:
                await message.channel.send(territory_name.strip() + " removed")
            except:
                pass
        else:
            try:
                await message.channel.send(territory_name + " is not a territory in the list")
            except:
                pass


async def on_command_start(message):
    msgs = message.content.split(" ")
    if len(msgs) < 2:
        await correct_command_start(message.channel)
        return
    if msgs[1] == 'chart':
        await on_command_start_chart(message)
    elif msgs[1] == 'missing':
        await on_command_start_missing(message)
    elif msgs[1] == "exchanges":
        await on_command_start_exchange(message)
    elif msgs[1] == "alert":
        await on_command_start_alerts(message)
    else:
        await correct_command_start(message.channel)
        return
    write()


async def on_command_start_chart(message):
    msgs = message.content.split(" ")
    if len(msgs) < 3:
        await correct_command_start_chart(message.channel)
        return
    list_name = msgs[2]
    if list_name in lists[str(message.author.id)]:
        try:
            try:
                mess = await message.channel.send("This could take up to 30 seconds to load")
            except (discord.errors.Forbidden, discord.errors.NotFound):
                return

            charts[str(message.author.id)][list_name] = {"message": mess, "page": 0, "reactions": False}
        except:
            pass
    else:
        await is_not_a_list(list_name, message.channel)


async def on_command_start_missing(message):
    msgs = message.content.split(" ")
    if len(msgs) < 3:
        await correct_command_start_chart(message.channel)
        return
    list_name = msgs[2]
    if list_name in lists[str(message.author.id)]:
        try:
            try:
                mess = await message.channel.send("This could take up to 30 seconds to load")
            except (discord.errors.NotFound, discord.errors.Forbidden):
                return
            missings[str(message.author.id)][list_name] = {
                "message": mess, "page": 0,
                "reactions": False}
        except:
            pass
    else:
        await is_not_a_list(list_name, message.channel)


async def on_command_start_exchange(message):
    msgs = message.content.split(" ")
    if len(msgs) < 3:
        await correct_command_start_tracking_territories(message.channel)
        return
    list_name = msgs[2]
    if list_name in lists[str(message.author.id)]:
        try:
            await message.channel.send(list_name + " territory exchanges will happen here")
        except (discord.errors.Forbidden, discord.errors.NotFound):
            return
        except:
            pass
        exchanges[str(message.author.id)][list_name] = {"channel": message.channel}

    else:
        await is_not_a_list(list_name, message.channel)


async def on_command_start_alerts(message):
    msgs = message.content.split(" ")
    if len(msgs) != 5 or not msgs[4].isdigit():
        await correct_command_start_alert(message.channel)
        return
    list_name = msgs[2]
    role = msgs[3]
    threshold = int(msgs[4])
    # TODO ROLE

    try:
        await message.channel.send(
            "Alerts will be sent here if " + list_name + " loses " + str(threshold + 1) + " territories")
    except (discord.errors.NotFound, discord.errors.Forbidden):
        return
    except:
        pass
    alerts[str(message.author.id)][list_name] = {"channel": message.channel, "role": role, "threshold": threshold,
                                                 "safe": False}


async def on_command_remove(message):
    msgs = message.content.split(" ")
    if len(msgs) < 2:
        await correct_command_remove(message.channel)
        return
    if msgs[1] == 'charts':
        if len(msgs) < 3:
            await correct_command_remove(message.channel)
            return
        list_name = " ".join(msgs[2:])
        if list_name in charts[str(message.author.id)]:
            try:
                charts[str(message.author.id)].__delitem__(list_name)
            except KeyError:
                # already gone
                pass
            try:
                await message.channel.send(list_name + " removed from charts")
            except:
                pass
        else:
            try:
                await message.channel.send(list_name + " is not in charts")
            except:
                pass
        write()
    elif msgs[1] == 'missings':
        if len(msgs) < 3:
            await correct_command_remove(message.channel)
            return
        list_name = " ".join(msgs[2:])
        if list_name in missings[str(message.author.id)]:
            try:
                missings[str(message.author.id)].__delitem__(list_name)
            except KeyError:
                # already gone
                pass
            try:
                await message.channel.send(list_name + " removed from missing")
            except:
                pass
        else:
            try:
                await message.channel.send(list_name + " is not in missing")
            except:
                pass
        write()
    elif msgs[1] == 'exchanges':
        if len(msgs) < 3:
            await correct_command_remove(message.channel)
            return
        list_name = " ".join(msgs[2:])
        if list_name in exchanges[str(message.author.id)]:
            try:
                exchanges[str(message.author.id)].__delitem__(list_name)
            except KeyError:
                # already gone
                pass
            try:
                await message.channel.send(list_name + " removed from exchanges")
            except:
                pass
        else:
            try:
                await message.channel.send(list_name + " is not in exchanges")
            except:
                pass
        write()
    elif msgs[1] == 'alerts':
        if len(msgs) < 3:
            await correct_command_remove(message.channel)
            return
        list_name = " ".join(msgs[2:])
        if list_name in alerts[str(message.author.id)]:
            try:
                alerts[str(message.author.id)].__delitem__(list_name)
            except KeyError:
                # already gone
                pass
            try:
                await message.channel.send(list_name + " removed from alerts")
            except:
                pass
        else:
            try:
                await message.channel.send(list_name + " is not in alerts")
            except:
                pass
        write()
    else:
        list_name = ' '.join(msgs[2:])
        if list_name in lists[str(message.author.id)]:
            try:
                lists[str(message.author.id)].__delitem__(list_name)
            except KeyError:
                # already gone
                pass
            try:
                await message.channel.send(list_name + " removed from lists")
            except:
                pass
        else:
            try:
                await is_not_a_list(list_name, message.channel)
            except:
                pass


def new_client(client_id):
    lists[client_id] = dict()
    charts[client_id] = dict()
    missings[client_id] = dict()
    exchanges[client_id] = dict()
    alerts[client_id] = dict()


async def correct_command_list_remove(channel):
    '''
    sends a correct usage of the !list remove command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "list remove (guilds/territories)")

    except:
        pass


async def correct_command_list_all(channel):
    '''
        sends a correct usage of the !list all command
        :param channel: the channel to send the message to
        :return:
        '''
    try:
        await channel.send(prefix + "list all <list_name>")

    except:
        pass


async def correct_command_list_remove_guild(channel):
    '''
    sends a correct usage of the !list remove command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "list remove guild <list name> guild,guild...")

    except:
        pass


async def correct_command_list_remove_territories(channel):
    '''
    sends a correct usage of the !list remove command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "list remove territories <list name> territory,territory...")

    except:
        pass


async def correct_command_list_add(channel):
    '''
    sends a correct usage of the !list add command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "list add (guilds/territories) <list name> territory,territory...")

    except:
        pass


async def correct_command_list_add_guild(channel):
    '''
    sends a correct usage of the !list add command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "list add guilds <list name> guild,guild...")

    except:
        pass


async def correct_command_list_add_territories(channel):
    '''
    sends a correct usage of the !list add command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "list add territories <list name> territory,territory...")

    except:
        pass


async def correct_command_list_copyterritories(channel):
    '''
    sends a correct usage of the !list copyterritories command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "list copyterritories <list name> <guild name>")

    except:
        pass


async def correct_command_list_create(channel):
    '''
    sends a correct usage of the !list create command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "list create <list name> <rightful owner of terrs>")

    except:
        pass


async def correct_command_list(channel):
    '''
    sends a correct usage of the  !list command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "list (create/copyterritories/add/remove)")

    except:
        pass


async def correct_command_full_missing(channel):
    '''
    sends a correct usage of the !full_missing command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "full_missing (guilds/territories) (add/remove) <territory/guild name>")

    except:
        pass


async def correct_command_start(channel):
    '''
    sends a correct usage of the !start command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "start (chart/missing/exchanges/alerts/full_missing)")

    except:
        pass


async def correct_command_remove(channel):
    '''
    sends a correct usage of the !remove command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "remove (chart/missing/exchanges/alert) <list name>")

    except:
        pass


async def correct_command_start_tracking_territories(channel):
    '''
    sends a correct usage of the !start territories command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "start territories <list name>")

    except:
        pass


async def correct_command_start_missing(channel):
    '''
    sends a correct usage of the !start missing command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "start missing <list name>")

    except:
        pass


async def correct_command_start_chart(channel):
    '''
    sends a correct usage of the !start chart command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "start chart <list name>")

    except:
        pass


async def correct_command_start_alert(channel):
    '''
    sends a correct usage of the !start alert command
    :param channel: the channel to send the message to
    :return:
    '''
    try:
        await channel.send(prefix + "start alert <list name> <\\\\@role name> <threshold>")

    except:
        pass


async def is_not_a_list(list_name, chan):
    '''
    tells the user that list_name is not one of thier lists
    :param list_name: the list name they are trying to use
    :param chan: the channel to send the message to
    :return:
    '''
    try:
        await chan.send(list_name + " is not a list")

    except:
        pass


async def remove_reactions(info):
    try:
        await info['message'].remove_reaction("⬅", client.get_user(bot_user))
    except:
        pass
    try:
        await info['message'].remove_reaction("➡", client.get_user(bot_user))
    except:
        pass


async def add_reactions(info):
    try:
        await info['message'].add_reaction("⬅")
    except:
        pass
    try:
        await info['message'].add_reaction("➡")
    except:
        pass
    info['reactions'] = True


def time_subtract(api_format_aquired, time_format_now):
    date_past = datetime.datetime.strptime(api_format_aquired, "%Y-%m-%d %H:%M:%S")
    date_now = datetime.datetime.fromtimestamp(time_format_now)
    date_difference = date_now - date_past
    return "{:<3}".format(str(date_difference.days)) + "d " + "{:<2}".format(
        str(date_difference.seconds // 3600)) + "h " + "{:2}".format(str(
        date_difference.seconds % 3600 // 60)) + "m"


async def send_trace():
    string = traceback.format_exc()
    msgs = list()
    while True:
        if len(string) < 1998:
            msgs.append(string)
            break
        else:
            msgs.append(str(string[:1998]))
            string = string[1997:]
    for i in msgs:
        try:
            await client.get_user(debug_person).send(i)
        except client_exceptions.ClientOSError:
            await asyncio.sleep(1)
            continue
        except:
            pass


async def read():
    with open("data.txt") as file:
        count = 0
        for line in file:
            loaded = loads(line.strip())
            if count == 0:
                for element in loaded:
                    lists[element] = loaded[element]
            elif count == 1:
                for client_id in loaded:
                    charts[client_id] = loaded[client_id]
                    for list_name in list(charts[client_id].keys()):
                        while True:
                            try:
                                charts[client_id][list_name]['message'] = await client.get_channel(
                                    charts[client_id][list_name]['message']).send(
                                    "This could take up to 30 seconds to load")
                            except (discord.errors.Forbidden, discord.errors.NotFound):
                                await asyncio.sleep(5)
                                continue
                            except:
                                try:
                                    charts[client_id].__delitem__(list_name)
                                except KeyError:
                                    # already gone
                                    pass
                            break
            elif count == 2:
                for client_id in loaded:
                    missings[client_id] = loaded[client_id]
                    for list_name in list(missings[client_id].keys()):
                        while True:
                            try:
                                missings[client_id][list_name]['message'] = await client.get_channel(
                                    missings[client_id][list_name]['message']).send(
                                    "This could take up to 30 seconds to load")
                            except (discord.errors.Forbidden, discord.errors.NotFound):
                                await asyncio.sleep(5)
                                continue
                            except:
                                try:
                                    charts[client_id].__delitem__(list_name)
                                except KeyError:
                                    # already gone
                                    pass
                            break
            elif count == 3:
                for client_id in loaded:
                    exchanges[client_id] = loaded[client_id]
                    for list_name in list(exchanges[client_id].keys()):
                        exchanges[client_id][list_name]['channel'] = client.get_channel(
                            exchanges[client_id][list_name]['channel'])
            elif count == 4:
                for client_id in loaded:
                    alerts[client_id] = loaded[client_id]
                    for list_name in list(alerts[client_id].keys()):
                        alerts[client_id][list_name]['channel'] = client.get_channel(
                            alerts[client_id][list_name]['channel'])

            count += 1


def readable_lists():
    return lists


def readable_charts():
    readable = dict()
    for client_id in charts:
        readable[client_id] = dict()
        for list_name in list(charts[client_id].keys()):
            readable[client_id][list_name] = dict()
            for element in charts[client_id][list_name]:
                if element == 'message':
                    readable[client_id][list_name][element] = charts[client_id][list_name][element].channel.id
                elif element == 'reactions':
                    readable[client_id][list_name][element] = False
                else:
                    readable[client_id][list_name][element] = charts[client_id][list_name][element]
    return readable


def readable_missings():
    readable = dict()
    for client_id in missings:
        readable[client_id] = dict()
        for list_name in list(missings[client_id].keys()):
            readable[client_id][list_name] = dict()
            for element in missings[client_id][list_name]:
                if element == 'message':
                    readable[client_id][list_name][element] = missings[client_id][list_name][element].channel.id
                elif element == 'reactions':
                    readable[client_id][list_name][element] = False
                else:
                    readable[client_id][list_name][element] = missings[client_id][list_name][element]
    return readable


def readable_exchanges():
    readable = dict()
    for client_id in exchanges:
        readable[client_id] = dict()
        for list_name in list(exchanges[client_id].keys()):
            readable[client_id][list_name] = dict()
            for element in exchanges[client_id][list_name]:
                if element == 'channel':
                    readable[client_id][list_name][element] = exchanges[client_id][list_name][element].id
                else:
                    readable[client_id][list_name][element] = exchanges[client_id][list_name][element]
    return readable


def readable_alerts():
    readable = dict()
    for client_id in alerts:
        readable[client_id] = dict()
        for list_name in list(alerts[client_id].keys()):
            readable[client_id][list_name] = dict()
            for element in alerts[client_id][list_name]:
                if element == 'channel':
                    readable[client_id][list_name][element] = alerts[client_id][list_name][element].id
                else:
                    readable[client_id][list_name][element] = alerts[client_id][list_name][element]
    return readable


def write():
    temp_lists = readable_lists()
    temp_charts = readable_charts()
    temp_missings = readable_missings()
    temp_exchanges = readable_exchanges()
    temp_alerts = readable_alerts()
    string = (
            dumps(temp_lists) + '\n' +
            dumps(temp_charts) + '\n' +
            dumps(temp_missings) + '\n' +
            dumps(temp_exchanges) + '\n' +
            dumps(temp_alerts) + '\n')
    with open("data.txt", "w") as file:
        file.write(string)


async def get_terr_list():
    while True:
        try:
            return loads(
                urllib.request.urlopen(
                    "https://api.wynncraft.com/public_api.php?action=territoryList").readline().decode("utf-8"))
        except:
            await asyncio.sleep(10)


class DisconnectException(Exception):
    '''
    Just a custom Exception
    '''
    pass


def client_runner():
    '''
    start the bot
    :return: never
    '''
    while True:
        try:
            client.run(login)
            print("Wow")
        except:
            print("F")
            pass
        finally:
            begun[0] = False


commands_set = {"help": on_command_help, "info": on_command_info, "instructions": on_command_instructions,
                "list": on_command_list, "start": on_command_start, "remove": on_command_remove,
                "show_lists": on_command_show_lists, "print_terrs": on_command_print_terrs, "write": on_command_write,
                "show": on_command_show}

if __name__ == "__main__":
    client_runner()
