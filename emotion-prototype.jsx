import React, { useState, useEffect, useRef } from "react";

/* =====================================================================
   Phase 0.5 프로토타입 — 감정 기반 유튜브 추천
   목적: taxonomy.yaml의 문구가 실제 화면에서 어떤 온도로 읽히는지 확인
   - 분류 로직(normalize + 사전 매칭)은 Phase 3에 그대로 이식할 코드
   - 영상은 샘플 데이터 (아티팩트는 외부 통신 불가)
   - 저장은 메모리 (실제 앱에서는 IndexedDB)
   ===================================================================== */

const T = {
  ink: "#141E24",
  inkDeep: "#0B1216",
  plum: "#221A28",
  mist: "#E9EEEA",
  muted: "#8DA29E",
  jade: "#7FB3A3",
  sand: "#E0C49B",
};

const norm = (s) =>
  s
    .toLowerCase()
    .replace(/[^\w가-힣ㄱ-ㅎㅏ-ㅣa-z0-9]/g, "")
    .replace(/(.)\1{2,}/g, "$1$1")
    .replace(/ㅜ/g, "ㅠ");

const CRISIS = ["죽고싶","죽어버리","사라지고싶","없어지고싶","자해","살기싫","끝내고싶","그만살","살아야할이유","눈뜨고싶지않"];

const DATA = [
  { id:"anxiety", label:"불안", subs:[
    { id:"anxiety.restless", label:"초조함",
      kw:["초조","조급","안절부절","마음이급","발동동","시간이없","쫓기","애가타","조바심","진정이안","급해죽겠"],
      emp:["마음이 자꾸 앞서 달려가는 날이네요. 잠시 같이 숨을 골라요.","조급한 마음이 느껴져요. 여기서는 좀 천천히 가도 돼요.","마음이 먼저 뛰어가고 있군요. 잠깐 붙잡아둬요.","숨이 가빠지는 하루였죠. 여기서 한 박자 쉬어요."],
      clo:["서두르지 않아도 괜찮은 저녁이에요.","마음이 앞서면 몸이 힘들어요. 좀 쉬어요.","천천히 가도 도착해요.","조급한 마음, 여기 두고 가요."],
      vid:["빗소리와 함께하는 90분","호흡을 고르는 5분 명상","느린 피아노 연주 모음","창밖 비 오는 밤"] },
    { id:"anxiety.worry", label:"걱정",
      kw:["걱정","근심","신경쓰여","어떡하지","잘못되면","마음에걸려","생각이많","잠이안와","머리가복잡","실패할까봐","노심초사"],
      emp:["머릿속에 걱정이 자리를 크게 차지하고 있군요. 잠시 내려놓아도 돼요.","생각이 꼬리를 무는 날이네요. 여기서 한 번 끊어가요.","아직 오지 않은 일에 마음을 많이 쓰고 계시군요.","걱정이 많다는 건 그만큼 아끼는 게 있다는 뜻이에요."],
      clo:["걱정한다고 달라지지 않는 일은, 오늘은 여기 두고 가요.","오늘 몫의 걱정은 여기까지예요.","답 없는 질문은 잠시 접어둬요.","내일의 걱정은 내일의 당신이 더 잘해요."],
      vid:["생각을 정리하는 밤 산책","마음이 편해지는 이야기","숲속 새소리 3시간","잠들기 전 마음챙김"] },
    { id:"anxiety.tension", label:"긴장",
      kw:["긴장","떨려","면접","발표","시험","심장이두근","손에땀","압박감","부담돼","실수할까봐","목소리가떨"],
      emp:["몸도 마음도 잔뜩 힘이 들어가 있네요. 어깨부터 살짝 풀어볼까요.","긴장으로 굳어 있는 게 느껴져요. 숨부터 한 번 쉬어요.","중요한 일을 앞두고 계시군요. 떨리는 게 당연해요.","잘하고 싶은 마음이 커서 그런 거예요."],
      clo:["긴장한다는 건 그만큼 진심이라는 뜻이기도 해요.","떨면서 해내는 사람이 제일 멋져요.","힘 빼는 것도 준비의 일부예요.","잘될 거예요. 그러니 오늘은 쉬어요."],
      vid:["어깨 풀어주는 10분 스트레칭","4-7-8 호흡법 가이드","차분해지는 첼로 연주","무대 전에 듣는 플레이리스트"] }]},

  { id:"anger", label:"분노", subs:[
    { id:"anger.irritation", label:"짜증",
      kw:["짜증","신경질","거슬려","예민","다싫","빡쳐","열받","킹받","귀찮게","꼴보기싫","어이없"],
      emp:["오늘은 사소한 것까지 거슬리는 날이었죠. 그럴 수 있어요.","신경이 곤두서 있군요. 잠깐 다른 데를 봐요.","작은 일에 화가 나는 건 이미 지쳐 있어서예요.","오늘은 좀 예민해도 되는 날로 해요."],
      clo:["짜증났던 하루도 여기서 한 템포 끊어가요.","기분은 곧 바뀌어요.","예민한 날엔 혼자 있어도 돼요.","내일은 조금 나을 거예요."],
      vid:["고양이 실수 모음 20분","묵은 서랍 정리 타임랩스","반죽 치대는 소리 ASMR","드라이브 플레이리스트"] },
    { id:"anger.unfair", label:"억울함",
      kw:["억울","왜나만","부당","불공평","오해","인정못받","서러워","분해","내탓아닌데","누명","차별"],
      emp:["내 마음 같지 않게 흘러간 일이 있었군요. 그 마음, 충분히 그럴 만해요.","억울한 일을 겪으셨네요. 여기서는 설명 안 해도 알아요.","알아주는 사람이 없어 더 힘드셨겠어요.","그렇게 느끼는 게 이상한 게 아니에요."],
      clo:["당신의 마음이 틀린 게 아니에요.","그 마음, 정당해요.","오늘은 스스로 편들어줘요.","알아주는 사람이 없어도 당신은 알잖아요."],
      vid:["마음을 다독이는 심리 이야기","감정을 정리하는 법","조용한 밤의 라디오","마음이 풀리는 기타 연주"] },
    { id:"anger.rage", label:"격분",
      kw:["화가나","폭발","참을수없","못참겠","미치겠","용서가안","부글부글","분노","돌아버리겠","소리지르고싶"],
      emp:["지금은 화가 많이 나 있는 상태예요. 우선 그 에너지를 안전하게 흘려보내요.","화가 크게 올라와 있군요. 지금은 아무 결정도 하지 말아요.","그럴 만한 일이 있었겠죠. 잠깐 식히고 가요.","터뜨리지 못한 화가 안에 남아 있군요."],
      clo:["화를 느끼는 건 잘못이 아니에요. 어떻게 흘려보내는지가 중요할 뿐.","지금은 아무 결정도 하지 말아요.","크게 난 불도 결국 잦아들어요.","화낸 자신을 미워하지 말아요."],
      vid:["파도가 부서지는 해안 1시간","15분 홈트레이닝","화를 가라앉히는 호흡","장작 타는 소리"] }]},

  { id:"frustration", label:"답답함", subs:[
    { id:"frustration.stuck", label:"막막함",
      kw:["막막","앞이캄캄","어디서부터","길이안보여","어떻게해야할지","감이안와","대책이없","방향을모르","캄캄"],
      emp:["앞이 잘 안 보이는 기분이군요. 지금은 방향보다 한 걸음이면 충분해요.","막막한 시간을 지나고 계시네요. 다 알고 시작한 사람은 없어요.","어디서부터 손대야 할지 모르겠는 날이죠.","캄캄하게 느껴질 땐 멀리 보지 않아도 돼요."],
      clo:["막막할 때는 크게 보지 말고, 오늘 하나만 봐요.","길은 걷다 보면 생겨요.","한 걸음이면 충분한 날이에요.","모르는 채로 있어도 괜찮아요."],
      vid:["천천히 걷는 새벽 산책","길을 잃어본 사람들의 이야기","마음 정리 저널링","안개 낀 숲 풍경"] },
    { id:"frustration.blocked", label:"진전 없음",
      kw:["안풀려","제자리","진도가안","벽에막힌","노력해도","성과가없","정체","나아지지않","되는일이없"],
      emp:["애쓰는데 잘 안 풀리는 시간을 지나고 계시네요. 멈춘 게 아니라 쌓이는 중이에요.","제자리인 것 같아 답답하시죠. 안 보여도 자라고 있어요.","계속 벽에 부딪히는 기분이겠어요.","오래 버티고 계셨네요. 그게 이미 대단한 거예요."],
      clo:["잘 안 풀리는 날 쉬어가는 것도 실력이에요.","안 되는 날도 지나가요.","오래 붙든 만큼 가까워졌어요.","오늘의 결과가 전부는 아니에요."],
      vid:["몰입을 돕는 로파이 3시간","슬럼프를 지나온 사람들","작은 루틴 브이로그","한적한 기차 창밖"] },
    { id:"frustration.suppressed", label:"억눌림",
      kw:["말못하고","참고있","속으로삭","숨막혀","체한것같","눈치보느라","꾹참","억눌","가슴이답답","하고싶은말"],
      emp:["하고 싶은 말을 삼키고 계셨군요. 여기서는 그 마음 그대로 두어도 돼요.","속에 담아둔 게 많아 보여요. 꺼내지 않아도 괜찮아요.","눈치 보며 참느라 애쓰셨네요.","가슴에 뭐가 얹힌 것 같으시겠어요."],
      clo:["참는 게 익숙해도, 당신 마음이 제일 먼저예요.","참느라 애쓴 하루, 수고했어요.","다 말하지 않아도 괜찮아요.","속엣말은 언젠가 꺼내도 돼요."],
      vid:["밤에 듣는 사연 라디오","후련해지는 노래 모음","마음을 표현하는 연습","텅 빈 바다 앞에서"] }]},

  { id:"sadness", label:"우울", subs:[
    { id:"sadness.sorrow", label:"슬픔",
      kw:["슬퍼","눈물이","울고싶","마음이아파","울적","우울","가라앉","마음이무거","웃음이안나","ㅠㅠ"],
      emp:["마음이 많이 무거운 날이네요. 억지로 밝아지지 않아도 괜찮아요.","오늘은 마음이 많이 가라앉았군요. 그대로 있어도 돼요.","힘든 하루였겠어요. 여기서 좀 쉬었다 가요.","이유가 없어도 슬플 수 있어요."],
      clo:["오늘 이 마음을 알아차린 것만으로 충분해요.","괜찮아지려 애쓰지 않아도 돼요.","이 밤이 지나면 조금은 나아요.","여기까지 온 것만으로 충분해요."],
      vid:["따뜻한 오후의 햇살 풍경","마음을 감싸는 피아노","조용한 시골 브이로그","고양이와 보내는 하루"] },
    { id:"sadness.lonely", label:"외로움",
      kw:["외로워","혼자","쓸쓸","허전","그리워","아무도없","공허","말할사람이없","혼밥","소외"],
      emp:["곁이 허전하게 느껴지는 시간이군요. 지금 이 순간은 혼자가 아니에요.","외로운 마음이 느껴져요. 오늘은 여기 같이 있을게요.","혼자인 것 같은 밤이죠. 그 마음 알아요.","연락할 데가 없는 날이 있어요. 오늘은 여기가 있잖아요."],
      clo:["외로움을 느낀다는 건, 연결을 아는 사람이라는 뜻이에요.","오늘 밤은 여기 같이 있을게요.","외로운 마음을 탓하지 말아요.","당신은 혼자가 아니에요."],
      vid:["같이 공부하는 4시간","심야 라디오 사연","캠핑장의 모닥불","누군가의 평범한 하루"] },
    { id:"sadness.loss", label:"상실감",
      kw:["잃었","떠나보냈","이별","헤어졌","텅빈","다시못","보고싶","빈자리","되돌릴수없"],
      emp:["소중한 무언가를 떠나보내셨군요. 천천히, 당신의 속도로 지나가도 돼요.","빈자리가 크게 느껴지는 시간이네요.","그리운 마음이 있으시군요. 그건 사랑했다는 증거예요.","정리하려 애쓰지 않아도 돼요."],
      clo:["잊는 게 아니라, 품고 살아가는 법을 배우는 중이에요.","서둘러 정리하지 않아도 돼요.","기억하는 게 잘 지내는 거예요.","그리움도 사랑의 일부예요."],
      vid:["마음을 감싸주는 첼로","회복에 관한 짧은 다큐","해 지는 바다","천천히 흐르는 강"] }]},

  { id:"exhaustion", label:"지침", subs:[
    { id:"exhaustion.burnout", label:"번아웃",
      kw:["번아웃","다놓고싶","소진","방전","탈진","쉬고싶","그만두고싶","더는못하겠","버틸수가","회의감"],
      emp:["오래 달려오셨네요. 지친 건 약해서가 아니라 열심히였다는 증거예요.","다 놓고 싶은 마음이 드시는군요. 그럴 만큼 애쓰셨어요.","여기까지 오느라 많이 소진되셨네요.","이제 좀 멈춰도 돼요. 무너지지 않아요."],
      clo:["오늘은 회복도 일이에요. 아무것도 안 해도 돼요.","멈춰도 무너지지 않아요.","여기까지 온 게 대단해요.","쉬어도 된다고 말해줄게요."],
      vid:["아무것도 안 하는 30분","시골집의 느린 하루","산속 오두막 풍경","쉼에 관한 이야기"] },
    { id:"exhaustion.tired", label:"피로",
      kw:["피곤","지쳤","졸려","힘이없","몸이무거","눕고싶","기운이없","못잤","야근","축처"],
      emp:["몸이 많이 무겁죠. 오늘은 몸의 소리를 먼저 들어줘요.","많이 피곤하시군요. 오늘은 일찍 쉬어요.","지친 하루였네요. 설명 말고 휴식이 필요할 때예요.","몸이 보내는 신호는 대체로 맞아요."],
      clo:["잘 쉬는 것도 내일을 위한 준비예요.","오늘은 일찍 자요.","몸이 먼저예요.","내일은 조금 가벼울 거예요."],
      vid:["숙면을 부르는 저주파 8시간","자기 전 10분 스트레칭","빗소리 백색소음","어두운 방의 ASMR"] },
    { id:"exhaustion.listless", label:"의욕 없음",
      kw:["의욕이없","하기싫","귀찮","무기력","손에안잡혀","멍하니","늘어져","미루","집중이안"],
      emp:["아무것도 하기 싫은 날이군요. 그런 날은 그런 대로 의미가 있어요.","의욕이 안 나는 시기죠. 억지로 끌어올리지 않아도 돼요.","손에 잡히는 게 없는 날이네요.","가만히 있는 것도 하고 있는 거예요."],
      clo:["시동은 천천히 걸어도 돼요.","오늘은 누워 있어도 돼요.","아무것도 안 한 날도 괜찮아요.","기준을 낮춰도 돼요."],
      vid:["가볍게 보는 일상 브이로그","10분이면 되는 아침 루틴","웃긴 짤 모음","창가에서 보는 구름"] }]},

  { id:"joy", label:"기쁨", subs:[
    { id:"joy.proud", label:"뿌듯함",
      kw:["뿌듯","해냈","성취","자랑스러","합격","붙었","성공했","완성했","끝냈","보람","목표달성"],
      emp:["해내셨군요! 그 성취, 마음껏 누리셔도 돼요.","축하드려요. 쌓아온 시간이 만든 결과예요.","오늘은 스스로를 실컷 칭찬해도 되는 날이에요.","뿌듯한 소식이네요. 저까지 기분이 좋아요."],
      clo:["오늘의 당신, 충분히 자랑스러워요.","오늘은 실컷 기뻐해요.","고생한 만큼 누려요.","정말 잘하셨어요."],
      vid:["축하할 때 듣는 플레이리스트","해낸 사람들의 이야기","혼자 여는 작은 파티","기분 좋아지는 영상 모음"] },
    { id:"joy.delight", label:"즐거움",
      kw:["즐거워","신나","재밌","행복해","웃음이","기분좋","최고야","날아갈것","텐션","ㅋㅋ"],
      emp:["기분 좋은 에너지가 느껴져요. 이 기분, 더 크게 즐겨봐요.","오늘 참 좋은 날이었나 봐요!","즐거운 마음이 여기까지 전해져요.","이런 날은 아낌없이 즐겨요."],
      clo:["즐거운 순간은 오래 기억해두기로 해요.","오늘 같은 날이 자주 오길.","기분 좋은 날은 아껴 쓰지 말아요.","웃은 만큼 좋은 하루였어요."],
      vid:["신나는 드라이브 플레이리스트","웃음 터지는 영상 모음","춤추고 싶어지는 음악","축제의 밤 풍경"] },
    { id:"joy.grateful", label:"감사",
      kw:["감사","고마워","다행","덕분에","감동","마음이따뜻","울컥","뭉클","위로받","힘이됐"],
      emp:["따뜻한 마음이 가득한 날이네요. 그 마음이 오래 머물기를.","고마움을 느낀 하루였군요. 그것만으로 좋은 날이에요.","마음이 따뜻해지는 일이 있었나 봐요.","감사할 줄 아는 마음이 참 귀해요."],
      clo:["감사할 줄 아는 마음이 가장 큰 재산이에요.","고마운 마음, 전해보는 건 어때요.","따뜻한 하루였네요.","좋은 마음이 오래 머물기를."],
      vid:["마음이 따뜻해지는 이야기","감사 일기 쓰는 밤","훈훈한 순간들","잔잔하고 따뜻한 음악"] }]},

  { id:"flutter", label:"설렘", subs:[
    { id:"flutter.anticipation", label:"기대",
      kw:["기대","기다려져","다가오","여행가","만날생각","손꼽아","내일이면","디데이","벌써부터"],
      emp:["좋은 일이 다가오고 있나 봐요. 기다리는 시간마저 선물이에요.","설레는 일이 기다리고 있군요!","기대하는 마음이 느껴져요. 그 마음 아껴두지 말아요.","좋은 예감이 드는 날이네요."],
      clo:["기다림이 즐거운 건, 좋은 예감이라는 뜻이에요.","기다리는 시간도 좋은 시간이에요.","설렘을 아끼지 말아요.","기대해도 좋아요."],
      vid:["여행 준비하는 브이로그","기분 좋은 아침 음악","떠나기 전날 밤","새로운 시작 응원 영상"] },
    { id:"flutter.thrill", label:"두근거림",
      kw:["두근","설레","심쿵","첫만남","좋아하는사람","고백","썸","자꾸생각나","연락올까"],
      emp:["심장이 말을 거는 날이네요. 그 떨림을 즐겨봐요.","두근거리는 마음이 전해져요.","설레는 일이 있으시군요. 오늘 기분 참 좋겠어요.","이런 떨림, 자주 오지 않아요."],
      clo:["이 떨림, 놓치지 말고 충분히 느껴요.","오늘의 이 기분, 기억해둬요.","떨림은 살아있다는 증거예요.","충분히 설레도 돼요."],
      vid:["설렘 가득 플레이리스트","봄밤의 산책","감성 사진 찍는 법","좋아하는 마음에 관하여"] }]},

  { id:"calm", label:"평온", subs:[
    { id:"calm.ease", label:"여유",
      kw:["여유","한가","느긋","커피한잔","산책","늘어지게","휴일","쉬는날","뒹굴","나른한오후"],
      emp:["모처럼 여유로운 시간이네요. 이 온도를 그대로 유지해요.","느긋한 하루를 보내고 계시군요. 좋아요.","여유가 느껴지는 날이네요. 이런 시간이 소중해요.","천천히 흘러가는 오후군요."],
      clo:["이런 오후가 삶을 지탱해줘요.","이 속도 그대로 좋아요.","여유는 사치가 아니에요.","잘 쉬고 계시네요."],
      vid:["카페에서 듣는 재즈","느린 오후의 브이로그","창가의 화분 가꾸기","한적한 골목 산책"] },
    { id:"calm.stable", label:"안정",
      kw:["안정","평온","차분","고요","마음이편","잔잔","홀가분","개운","마음이가벼","괜찮아진"],
      emp:["마음이 잔잔한 호수 같은 상태네요. 좋은 신호예요.","평온한 마음이 느껴져요. 이런 날도 기록해둬요.","차분하고 안정된 하루를 보내고 계시군요.","마음이 정돈되어 있네요. 잘 지내고 계신 거예요."],
      clo:["잔잔한 마음, 오늘 하루의 선물이에요.","좋은 날도 기록해둬요.","평온함은 스스로 만든 거예요.","잘 지내고 계세요."],
      vid:["새벽의 고요한 풍경","마음챙김 명상 20분","책 읽을 때 듣는 음악","호수의 아침"] }]},

  { id:"boredom", label:"심심함", subs:[
    { id:"boredom.dull", label:"지루함",
      kw:["심심","지루","무료","할게없","시간이안가","따분","노잼","재미없","뭐하지","볼거없"],
      emp:["시간이 느리게 가는 날이군요. 가볍게 재미를 채워볼까요.","심심한 하루네요. 뭔가 재밌는 걸 찾아봐요.","무료한 시간이죠. 가볍게 볼 것들을 골라봤어요.","할 일 없는 날도 나쁘지 않아요."],
      clo:["심심함은 새로운 재미를 찾으라는 신호예요.","심심한 날도 나쁘지 않아요.","지루함에서 좋은 생각이 나와요.","무료할 여유가 있다는 것도 좋은 일이에요."],
      vid:["순삭되는 미스터리 이야기","세계의 신기한 장소들","몰입되는 짧은 다큐","웃긴 영상 모음"] },
    { id:"boredom.novelty", label:"새로운 자극",
      kw:["새로운거","색다른","자극이필요","뭔가배우고","도전하고싶","신선한","취미찾","변화가필요","안해본거"],
      emp:["뭔가 새로운 게 필요한 때네요. 낯선 세계로 잠깐 다녀와요.","색다른 걸 찾고 계시군요. 좋은 신호예요.","호기심이 생기는 날이네요. 어디까지 가볼까요.","익숙한 게 지겨워질 때가 변화의 시작이에요."],
      clo:["호기심이 살아있다는 건 마음이 건강하다는 증거예요.","작은 시도가 멀리 가요.","오늘 하나만 새로 알아도 충분해요.","낯선 것에서 시작돼요."],
      vid:["처음 해보는 취미 10가지","가보지 못한 도시 다큐","30분 만에 배우는 것들","요즘 화제인 신기한 것"] }]},
];

const CRISIS_BLOCK = {
  label: "지금 이 마음",
  msg: "지금 마음이 많이 힘드신 것 같아요. 혼자 견디지 않으셔도 됩니다. 전문 상담원과 이야기해보시는 건 어떨까요. 24시간 언제든 연결돼요.",
  res: [ {n:"자살예방 상담전화", t:"109"}, {n:"정신건강 위기상담전화", t:"1577-0199"} ],
  vid: ["파도 소리 긴 영상","호흡 이완 가이드","숲속의 아침 풍경","마음이 편안해지는 소리"],
  clo: ["오늘 이 마음을 꺼내주셔서 고마워요. 여기서 잠시 쉬었다 가요.","말해줘서 고마워요. 지금은 아무것도 하지 않아도 괜찮아요."],
};

const PLACEHOLDERS = [
  "오늘 마음, 어땠어요?",
  "지금 어떤 마음인지 편하게 적어주세요",
  "무슨 일이 있었나요?",
  "잘 정리되지 않아도 괜찮아요. 떠오르는 대로",
];
const LOADING_MSGS = ["마음을 읽는 중이에요","천천히 들여다보는 중이에요","어울리는 걸 찾는 중이에요"];

const pick = (arr, notIdx) => {
  if (arr.length === 1) return { v: arr[0], i: 0 };
  let i;
  do { i = Math.floor(Math.random() * arr.length); } while (i === notIdx);
  return { v: arr[i], i };
};

const greet = () => {
  const h = new Date().getHours();
  if (h < 6) return "늦은 시간까지 깨어 있네요";
  if (h < 12) return "좋은 아침이에요";
  if (h < 18) return "오후는 어떻게 지나가고 있나요";
  return "오늘 하루 수고했어요";
};

function classify(text) {
  const n = norm(text);
  if (!n) return { kind: "empty" };
  for (const k of CRISIS) if (n.includes(norm(k))) return { kind: "crisis" };
  let best = null;
  for (const cat of DATA)
    for (const s of cat.subs) {
      const hits = s.kw.filter((k) => n.includes(norm(k)));
      if (hits.length) {
        const score = hits.length * 1000 + hits.reduce((a, b) => a + b.length, 0);
        if (!best || score > best.score) best = { score, sub: s, cat, hits };
      }
    }
  return best ? { kind: "ok", ...best } : { kind: "nomatch" };
}

export default function App() {
  const [paced, setPaced] = useState(true);
  const [mode, setMode] = useState("text");
  const [text, setText] = useState("");
  const [phase, setPhase] = useState("input");
  const [result, setResult] = useState(null);
  const [ph] = useState(() => PLACEHOLDERS[Math.floor(Math.random() * PLACEHOLDERS.length)]);
  const [loadMsg, setLoadMsg] = useState(LOADING_MSGS[0]);
  const [selCat, setSelCat] = useState(null);
  const lastEmp = useRef({});
  const lastClo = useRef({});

  const show = (r) => {
    if (r.kind === "ok") {
      const e = pick(r.sub.emp, lastEmp.current[r.sub.id]);
      const c = pick(r.sub.clo, lastClo.current[r.sub.id]);
      lastEmp.current[r.sub.id] = e.i;
      lastClo.current[r.sub.id] = c.i;
      setResult({ ...r, empathy: e.v, closing: c.v });
    } else setResult(r);
    setPhase("result");
  };

  const run = (r) => {
    if (r.kind === "empty" || r.kind === "nomatch") { setResult(r); setPhase("result"); return; }
    if (!paced) { show(r); return; }
    setLoadMsg(LOADING_MSGS[Math.floor(Math.random() * LOADING_MSGS.length)]);
    setPhase("loading");
    setTimeout(() => show(r), 1000);
  };

  const reset = () => { setPhase("input"); setText(""); setSelCat(null); setResult(null); };

  const wrap = {
    minHeight: "100%", background: `radial-gradient(120% 90% at 50% 0%, ${T.plum} 0%, ${T.ink} 45%, ${T.inkDeep} 100%)`,
    color: T.mist, fontFamily: "'Noto Sans KR','Apple SD Gothic Neo',system-ui,sans-serif",
    padding: "40px 22px 56px", display: "flex", flexDirection: "column", alignItems: "center",
  };
  const serif = "'Nanum Myeongjo','Gowun Batang',serif";

  return (
    <div style={wrap}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Gowun+Batang:wght@400;700&family=Noto+Sans+KR:wght@300;400;500&display=swap');
        @keyframes breathe { 0%,100%{transform:scale(1);opacity:.30} 45%{transform:scale(1.20);opacity:.55} }
        @keyframes rise { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }
        .rise{animation:rise .7s ease both}
        .orb{animation:breathe 10s ease-in-out infinite}
        @media (prefers-reduced-motion: reduce){ .orb{animation:none} .rise{animation:none} }
        .vcard:hover{ border-color:${T.jade}66 !important; transform:translateY(-2px) }
        .vcard{ transition:all .25s ease }
        input:focus{ outline:none; border-bottom-color:${T.jade} !important }
        button{ font-family:inherit; cursor:pointer }
      `}</style>

      {/* 개발용 토글 */}
      <div style={{ display: "flex", gap: 8, alignSelf: "flex-end", marginBottom: 28, fontSize: 11 }}>
        {[["즉답 0ms", false], ["뜸 들이기 1000ms", true]].map(([l, v]) => (
          <button key={l} onClick={() => setPaced(v)} style={{
            padding: "5px 11px", borderRadius: 99, border: `1px solid ${paced === v ? T.jade : "#ffffff20"}`,
            background: paced === v ? `${T.jade}1f` : "transparent", color: paced === v ? T.jade : T.muted }}>{l}</button>
        ))}
      </div>

      <div style={{ width: "100%", maxWidth: 460 }}>
        {phase === "input" && (
          <div className="rise">
            <div style={{ position: "relative", height: 150, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 8 }}>
              <div className="orb" style={{ position: "absolute", width: 190, height: 190, borderRadius: "50%",
                background: `radial-gradient(circle, ${T.jade}55 0%, ${T.jade}00 68%)` }} />
              <div style={{ position: "relative", textAlign: "center" }}>
                <div style={{ fontSize: 12, letterSpacing: "0.22em", color: T.muted, marginBottom: 12 }}>오늘의 마음</div>
                <div style={{ fontFamily: serif, fontSize: 25, fontWeight: 400, lineHeight: 1.5 }}>{greet()}</div>
              </div>
            </div>

            {mode === "text" ? (
              <div style={{ marginTop: 30 }}>
                <input value={text} onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && run(classify(text))} placeholder={ph}
                  style={{ width: "100%", background: "transparent", border: "none", borderBottom: `1px solid #ffffff26`,
                    padding: "13px 2px", fontSize: 16, color: T.mist, fontFamily: "inherit" }} />
                <button onClick={() => run(classify(text))} style={{ width: "100%", marginTop: 26, padding: "14px",
                  borderRadius: 3, border: `1px solid ${T.jade}59`, background: `${T.jade}14`, color: T.jade, fontSize: 14, letterSpacing: "0.04em" }}>
                  마음 들여다보기
                </button>
                <button onClick={() => setMode("select")} style={{ width: "100%", marginTop: 14, background: "none", border: "none", color: T.muted, fontSize: 13 }}>
                  골라서 찾을래요
                </button>
              </div>
            ) : (
              <div style={{ marginTop: 30 }}>
                <div style={{ fontSize: 13, color: T.muted, marginBottom: 16 }}>
                  {selCat ? "조금 더 자세히 알려주실래요?" : "지금 마음에 가장 가까운 건 어느 쪽인가요?"}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {(selCat ? selCat.subs : DATA).map((it) => (
                    <button key={it.id} onClick={() => selCat ? run({ kind: "ok", sub: it, cat: selCat, hits: [] }) : setSelCat(it)}
                      style={{ padding: "9px 15px", borderRadius: 99, border: `1px solid #ffffff1f`,
                        background: "transparent", color: T.mist, fontSize: 14 }}>{it.label}</button>
                  ))}
                </div>
                <button onClick={() => selCat ? setSelCat(null) : setMode("text")}
                  style={{ marginTop: 26, background: "none", border: "none", color: T.muted, fontSize: 13, padding: 0 }}>
                  {selCat ? "← 다시 고르기" : "직접 적고 싶어요"}
                </button>
              </div>
            )}
          </div>
        )}

        {phase === "loading" && (
          <div style={{ height: 330, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
            <div className="orb" style={{ width: 130, height: 130, borderRadius: "50%",
              background: `radial-gradient(circle, ${T.jade}66 0%, ${T.jade}00 70%)`, animationDuration: "2.6s" }} />
            <div style={{ marginTop: 26, fontSize: 14, color: T.muted, letterSpacing: "0.05em" }}>{loadMsg}</div>
          </div>
        )}

        {phase === "result" && result.kind === "empty" && (
          <Msg t="한 단어여도 괜찮아요" s="말로 안 되면 골라서 찾아도 돼요" onBack={reset} serif={serif} />
        )}
        {phase === "result" && result.kind === "nomatch" && (
          <Msg t="제가 잘 못 알아들었어요" s="아래에서 가까운 마음을 골라주실래요?" onBack={() => { setMode("select"); reset(); }} back="골라서 찾기" serif={serif} />
        )}

        {phase === "result" && result.kind === "crisis" && (
          <div className="rise">
            <div style={{ border: `1px solid ${T.sand}4d`, background: `${T.sand}0f`, borderRadius: 4, padding: "22px 20px" }}>
              <div style={{ fontFamily: serif, fontSize: 17, lineHeight: 1.75, color: T.mist }}>{CRISIS_BLOCK.msg}</div>
              <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 9 }}>
                {CRISIS_BLOCK.res.map((r) => (
                  <div key={r.t} style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
                    padding: "12px 15px", border: `1px solid ${T.sand}40`, borderRadius: 3 }}>
                    <span style={{ fontSize: 13.5, color: T.mist }}>{r.n}</span>
                    <span style={{ fontFamily: serif, fontSize: 18, color: T.sand, letterSpacing: "0.04em" }}>{r.t}</span>
                  </div>
                ))}
              </div>
            </div>
            <div style={{ fontSize: 12.5, color: T.muted, margin: "30px 0 14px", letterSpacing: "0.03em" }}>지금 곁에 두면 좋을 것들</div>
            <Videos list={CRISIS_BLOCK.vid} />
            <Closing text={CRISIS_BLOCK.clo[0]} serif={serif} onBack={reset} />
          </div>
        )}

        {phase === "result" && result.kind === "ok" && (
          <div className="rise">
            <div style={{ fontSize: 11.5, letterSpacing: "0.2em", color: T.muted, marginBottom: 14 }}>
              {result.cat.label} · {result.sub.label}
            </div>
            <div style={{ fontFamily: serif, fontSize: 20, lineHeight: 1.8, color: T.mist }}>{result.empathy}</div>
            <div style={{ height: 1, background: "#ffffff14", margin: "30px 0 22px" }} />
            <Videos list={result.sub.vid} />
            <Closing text={result.closing} serif={serif} onBack={reset} />
          </div>
        )}
      </div>
    </div>
  );
}

const Videos = ({ list }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
    {list.map((v, i) => (
      <div key={i} className="vcard" style={{ display: "flex", gap: 13, alignItems: "center",
        border: "1px solid #ffffff14", borderRadius: 4, padding: 10, cursor: "pointer" }}>
        <div style={{ width: 76, height: 46, borderRadius: 2, flexShrink: 0,
          background: `linear-gradient(135deg, ${T.jade}2e, ${T.plum})` }} />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 14, color: T.mist, lineHeight: 1.45 }}>{v}</div>
          <div style={{ fontSize: 11, color: T.muted, marginTop: 4 }}>샘플 데이터</div>
        </div>
      </div>
    ))}
  </div>
);

const Closing = ({ text, serif, onBack }) => (
  <div style={{ marginTop: 32, textAlign: "center" }}>
    <div style={{ fontFamily: serif, fontSize: 14.5, color: T.muted, lineHeight: 1.8 }}>{text}</div>
    <button onClick={onBack} style={{ marginTop: 26, background: "none", border: "none", color: "#ffffff40", fontSize: 12.5 }}>
      다시 적어보기
    </button>
  </div>
);

const Msg = ({ t, s, onBack, back = "돌아가기", serif }) => (
  <div className="rise" style={{ textAlign: "center", paddingTop: 60 }}>
    <div style={{ fontFamily: serif, fontSize: 19, color: T.mist, lineHeight: 1.7 }}>{t}</div>
    <div style={{ fontSize: 13.5, color: T.muted, marginTop: 12 }}>{s}</div>
    <button onClick={onBack} style={{ marginTop: 30, padding: "11px 24px", borderRadius: 3,
      border: `1px solid ${T.jade}4d`, background: "transparent", color: T.jade, fontSize: 13 }}>{back}</button>
  </div>
);
