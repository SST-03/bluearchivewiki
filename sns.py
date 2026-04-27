from dataclasses import replace
import os
import re
import sys
import traceback
import orjson
import argparse

from jinja2 import Environment, FileSystemLoader

import wikitextparser as wtp
import wiki

from data import load_data, load_file_grouped
import shared.functions
from shared.MissingTranslations import MissingTranslations

from collections import defaultdict

PAGE_NAME_SNS_POSTS = "FruLink/Posts"
PAGE_NAME_SNS_CHARACTER_LIST = "Module:SNS/CharacterList"

class classSNSProfileData:
    #ID = -1;
    #ImageID = -1;
    #Namejp = "";
    #Idjp = "";
    #NameGlobal = "";
    #IdGlobal = "";
    def __init__ (self, id, ProfileImagePath, NameLocalizeKey, IdLocalizeKey):
        global data;
        self.ID = id;
        if not ProfileImagePath.startswith("UIs/01_Common/49_SNS/SNSProfile/SNS_Profile_Icon_"):
            raise ValueError("Can't reconize ProfileImagePath! It's value is:" + ProfileImagePath);
        self.ImageID = int(ProfileImagePath[50:])

        if NameLocalizeKey in data.localization:
            NameDict = data.localization[NameLocalizeKey];
            self.Namejp = NameDict.get("Jp");
            if self.Namejp is None:
                self.Namejp = ""
            self.NameGlobal = NameDict.get("En");
            if self.NameGlobal is None:
                self.NameGlobal = ""
        else:
            print(f'Cannot find SNS Name from key {NameLocalizeKey}!')

        if IdLocalizeKey in data.localization:
            IDDict = data.localization[IdLocalizeKey];
            self.Idjp = IDDict.get("Jp");
            if self.Idjp is None:
                self.Idjp = ""
            self.IdGlobal = IDDict.get("En");
            if self.IdGlobal is None:
                self.IdGlobal = ""
        else:
            print(f'Cannot find SNS ID from key {IdLocalizeKey}!')


class classSNSPostData:
    #Id = -1;
    #PosterId = -1;
    # SNSInfoId = -1;
    #PostText = "";
    #ImageIDs = [];
    #RepostNum = 0;
    #FavorNum = 0;
    #ReplyPostId = 0; # 0 means doesn't reply any post
    #ReposterId = 0; # 0 means there's no reposter
    #UnlockCondition_wikitext = ""
    #Replys = [] # used for output

    def __init__ (self, originalData: dict, server: str):
        global data;
        self.Id = originalData['Id'];
        self.PosterId = originalData['SNSProfileId']
        self.PostText = data.localization[originalData['PostTextLocalizeKey']][server].replace("\n","<br>");
        self.ImageIDs = [];
        for imagePath in originalData['PostImagePath']:
            if not imagePath.startswith("UIs/01_Common/49_SNS/SNSPostImg/"):
                raise ValueError("Can't reconize Path in PostImagePath! It's value is:" + imagePath);
            self.ImageIDs.append(imagePath[32:])
        # Repost Num in-game increases based on time, at the maximum of RepostMaxNum; same for FavorNum.
        self.RepostNum = originalData['RepostMaxNum'];
        self.FavorNum = originalData['FavorMaxNum'];
        self.ReplyPostId = originalData['MasterPostId'];
        self.ReposterId = originalData['RepostSNSProfileId'];
        global SNSPostUnlockData;
        self.UnlockCondition_wikitext = SNSPostUnlockData.get(self.Id);
        self.Replys = [];

    def addReply (self, data):
        self.Replys.append(data);

    def toWikitext (self):
        env = Environment(loader=FileSystemLoader(os.path.dirname(__file__)))
        template = env.get_template('templates/template_sns_card.txt')
        wikitext = template.render(data = self, images = "&".join(self.ImageIDs))
        replys = []
        #print(self.Id)
        for reply in self.Replys:
            #print(self.Id, reply.Id, len(self.Replys))
            if reply.Id == self.Id:
                raise ValueError(str(self.Id) + "WTF??? " + str(reply.Id));
            replys.append(reply.toWikitext());
        return wikitext + "".join(replys);



def getSNSUnlockCondition(List, ScenarioIDs_Stories):
    ConditionList = set();
    for ScenarioModeRewardId in List:
        for story in ScenarioIDs_Stories[ScenarioModeRewardId]:
            if story['SubType'] != "Series2":
                raise ValueError("Can't reconize what story it is! ModeId: " + story['ModeId']);
            if story['ModeType'] == "Prolugue":
                ConditionList.add("S2V_P_C{0}E{1}".format(story["ChapterId"],story["EpisodeId"]));
            elif story['ModeType'] == "SpecialOperation":
                ConditionList.add("S2V_EX_C{0}E{1}".format(story["ChapterId"],story["EpisodeId"]));
            else:
                ConditionList.add("S2V{0}C{1}E{2}".format(story["VolumeId"] - 1,story["ChapterId"],story["EpisodeId"]));
    return "/".join(ConditionList);


def init_data():
    global args, data;
    data = load_data(args['data_primary'], args['data_secondary'], args['translation'])

    # Step 1: init unlock condition of Post data
    # TODO: SNS Data in Global Server (After it has the data)
    global SNSPostUnlockData;
    SNSPostUnlockScenarioList = defaultdict(list); #key:RewardParcelId value:list[ScenarioModeRewardId]
    ScenarioIDs_Stories = defaultdict(list); #key:ScenarioModeRewardId value:list[ScenarioModeExcel]

    with open(os.path.join(args['data_primary'], 'DB', "ScenarioModeRewardExcelTable.json"),encoding="utf8") as f:
        dataScenarioModeRewardExcelTable = orjson.loads(f.read())
    for item in dataScenarioModeRewardExcelTable['DataList']:
        if item['RewardParcelType'] == "SNSPost":
            SNSPostUnlockScenarioList[item['RewardParcelId']].append(item['ScenarioModeRewardId'])


    with open(os.path.join(args['data_primary'], 'DB', "ScenarioModeExcelTable.json"),encoding="utf8") as f:
        ScenarioModeExcelTable = orjson.loads(f.read())
    for item in ScenarioModeExcelTable['DataList']:
        ScenarioIDs_Stories[item['ScenarioModeRewardId']].append(item);

    SNSPostUnlockData = defaultdict(lambda: "Unknown");
    for id, List in SNSPostUnlockScenarioList.items():
        SNSPostUnlockData[id] = getSNSUnlockCondition(List, ScenarioIDs_Stories);

    # Step 2: init Profile/Post Data
    global SNSProfileData, SNSPostData;
    SNSProfileData = {};

    with open(os.path.join(args['data_primary'], 'DB', "SNSProfileExcelTable.json"),encoding="utf8") as f:
        SNSProfileExcelTable_jp = orjson.loads(f.read())['DataList']

    # Is this really needed?
    #SNSProfileExcelTable_Global = load_file_grouped(args['data_secondary'], "SNSProfileExcelTable");

    for item in SNSProfileExcelTable_jp:
        SNSProfileData[item['Id']] = classSNSProfileData(item['Id'], item['ProfileImagePath'], item['NameLocalizeKey'], item['IdLocalizeKey'])

    SNSPostData = {};
    with open(os.path.join(args['data_primary'], 'DB', "SNSPostExcelTable.json"),encoding="utf8") as f:
        SNSPostExcelTable_jp = orjson.loads(f.read())['DataList'];
    for item in SNSPostExcelTable_jp:
        SNSPostData[item["Id"]] = classSNSPostData(item, 'Jp')

    for id, data in SNSPostData.items():
        if data.ReplyPostId != 0:
            # print(data.ReplyPostId, data.Id)
            SNSPostData[data.ReplyPostId].addReply(data);
            # print (SNSPostData[data.ReplyPostId].Id)
    

def generate():
    env = Environment(loader=FileSystemLoader(os.path.dirname(__file__)))
    global SNSProfileData, SNSPostData;

    SNSWikitexts_jp = [];
    for id, data in SNSPostData.items():
        # print(id, data.Id, "A")
        if data.ReplyPostId == 0:
            SNSWikitexts_jp.append(data.toWikitext());

    template = env.get_template('templates/page_sns.txt', None)
    wikitext = template.render(SNSWikitexts_jp = SNSWikitexts_jp);

    with open(os.path.join(args['outdir'], 'page_sns.txt'), 'w', encoding="utf8") as f:
        f.write(wikitext)
    if wiki.site != None:
        print(f"Publishing {PAGE_NAME_SNS_POSTS}")
        wiki.publish(PAGE_NAME_SNS_POSTS, wikitext, f"Updated {PAGE_NAME_SNS_POSTS} page")
    
    template = env.get_template('templates/template_sns_users.txt', None)
    wikitext = template.render(SNSProfileData = SNSProfileData);

    with open(os.path.join(args['outdir'], 'page_Module_SNS_UserData.lua'), 'w', encoding="utf8") as f:
        f.write(wikitext)
    if wiki.site != None:
        print(f"Publishing {PAGE_NAME_SNS_CHARACTER_LIST}")
        wiki.publish(PAGE_NAME_SNS_CHARACTER_LIST, wikitext, f"Updated {PAGE_NAME_SNS_CHARACTER_LIST} page")


    

def main():
    global args

    parser = argparse.ArgumentParser()

    parser.add_argument('-data_primary',    metavar='DIR', default='../ba-data/jp',     help='Fullest (JP) game version data')
    parser.add_argument('-data_secondary',  metavar='DIR', default='../ba-data/global', help='Secondary (Global) version data')
    parser.add_argument('-translation',     metavar='DIR', default='../bluearchivewiki/translation', help='Additional translations directory')
    parser.add_argument('-outdir',          metavar='DIR', default='out', help='Output directory')
    parser.add_argument('-wiki', nargs=2, metavar=('LOGIN', 'PASSWORD'), help='Publish data to wiki, requires wiki_template to be set')
    #parser.add_argument('-assets_dir',     metavar='DIR', default='C:/blue_archive_data/datamine/blue_archive/ui_textures', help='Directory with exported assets')
    # TODO: Automation of Export SNS Image

    args = vars(parser.parse_args())
    print(args)

    if args['wiki'] != None: 
        wiki.init(args)


    try:
        init_data()
        generate()
    except:
        parser.print_help()
        traceback.print_exc()

if __name__ == '__main__':
    main()
