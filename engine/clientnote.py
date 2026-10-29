"""
The deterministic client note, in plain language and in the client's own.

Two problems this solves, and they turn out to be the same problem.

The stand-in note used to be the finding's own `detail` string pasted into a
greeting. That string is written for the RM — "USD 10.3m falls due within
twelve months against USD 34.0m sellable at daily liquidity, of which USD 0.0m
sits outside any pledged portfolio" is exactly right for her and completely
wrong for the person receiving it. A client should not have to know what
"unpledged" means to read a letter about their own money.

And most of this book is not reported to in English. Labelling an English
paragraph with someone's reporting language is the workbench claiming work it
has not done, so until now the drawer simply refused to. Refusing is honest but
it is not useful.

Both are fixed here, in the engine, because the note contains figures and a
figure in this product comes out of engine/ or it does not appear. The frames
below are fixed sentences with slots; the slots are filled from the finding's
own `numbers`. Nothing is computed here that the finding did not already carry,
and nothing is translated at runtime — a sentence a compliance officer cannot
read back in both languages has no business being sent to a client.

What this is not: it is not the narration layer. `narrate.py` reads the RM's
notes and writes something specific to this client and this conversation, and
that is better. This is the floor, not the ceiling — the version that exists
with no key, no network and no model, and it says so on screen.
"""

# ── languages we can write ────────────────────────────────────────────────
# Keyed by the value in clients.reporting_language.
LANGS = ("English", "Traditional Chinese", "Simplified Chinese",
         "German", "Japanese", "Italian")

TAGS = {"English": "en", "Traditional Chinese": "zh-Hant",
        "Simplified Chinese": "zh-Hans", "German": "de",
        "Japanese": "ja", "Italian": "it"}

# ── who signs ─────────────────────────────────────────────────────────────
# The RM and the bank, as each language writes them. A name in a signature is
# not translated word for word — Clara Teo signs as 張慧玲 in Chinese — so
# these are fixed here, once, and engine/translate.py reads the same table to
# carry a signature across when it translates an amended note. Korean has a
# signature but no letter frames: there is no deterministic Korean note, only a
# translated one. Clara Teo and Halden Rowe are fictional.
RM_NAME = {
    "English": "Clara Teo",
    "Traditional Chinese": "張慧玲",
    "Simplified Chinese": "张慧玲",
    "German": "Clara Teo",
    "Japanese": "クララ・テオ",
    "Italian": "Clara Teo",
    "Korean": "클라라 테오",
}
BANK_NAME = {
    "English": "Halden Rowe",
    "Traditional Chinese": "翰登銀行",
    "Simplified Chinese": "翰登银行",
    "German": "Halden Rowe",
    "Japanese": "ハルデン・ロウ",
    "Italian": "Halden Rowe",
    "Korean": "할든 로우",
}

# ── the frame ─────────────────────────────────────────────────────────────
# greeting / opening / bridge into the suggestion / close / signature line.
FRAME = {
    "English": {
        "greeting": "Dear [[FIRST_NAME]],",
        "opening": "Before we next speak, there is one thing I would like to go "
                   "through with you.",
        "bridge": "What I would suggest",
        "close": "I would rather talk this through than leave it in an email. "
                 "I will call you this week.",
        "sign": "With best regards,\n" + RM_NAME["English"] + "\n" + BANK_NAME["English"],
    },
    "Traditional Chinese": {
        "greeting": "[[FIRST_NAME]] 您好：",
        "opening": "在我們下次談話之前，有一件事我想先和您說明。",
        "bridge": "我的建議",
        "close": "這件事我希望能當面或通話時談，而不是以電郵帶過。我本週會致電給您。",
        "sign": "順頌時祺\n" + RM_NAME["Traditional Chinese"] + "\n"
                + BANK_NAME["Traditional Chinese"],
    },
    "Simplified Chinese": {
        "greeting": "[[FIRST_NAME]] 您好：",
        "opening": "在我们下次交谈之前，有一件事我想先和您说明。",
        "bridge": "我的建议",
        "close": "这件事我希望能当面或通话时谈，而不是以邮件带过。我本周会致电给您。",
        "sign": "顺颂时祺\n" + RM_NAME["Simplified Chinese"] + "\n"
                + BANK_NAME["Simplified Chinese"],
    },
    "German": {
        "greeting": "Sehr geehrte(r) [[FIRST_NAME]],",
        "opening": "vor unserem nächsten Gespräch möchte ich einen Punkt mit Ihnen "
                   "durchgehen.",
        "bridge": "Mein Vorschlag",
        "close": "Ich würde das lieber persönlich besprechen als per E-Mail. Ich "
                 "rufe Sie diese Woche an.",
        "sign": "Mit freundlichen Grüssen\n" + RM_NAME["German"] + "\n" + BANK_NAME["German"],
    },
    "Japanese": {
        "greeting": "[[FIRST_NAME]] 様",
        "opening": "次回お話しする前に、一点お伝えしておきたいことがございます。",
        "bridge": "ご提案",
        "close": "本件はメールで済ませるよりも、直接お話しさせていただければと存じます。"
                 "今週中にお電話いたします。",
        "sign": "何卒よろしくお願い申し上げます。\n" + RM_NAME["Japanese"] + "\n"
                + BANK_NAME["Japanese"],
    },
    "Italian": {
        "greeting": "Gentile [[FIRST_NAME]],",
        "opening": "prima del nostro prossimo colloquio vorrei affrontare con Lei "
                   "un punto.",
        "bridge": "Il mio suggerimento",
        "close": "Preferirei parlarne di persona piuttosto che per e-mail. La "
                 "chiamo questa settimana.",
        "sign": "Cordiali saluti,\n" + RM_NAME["Italian"] + "\n" + BANK_NAME["Italian"],
    },
}

# The sign-off alone, for a note the model drafted: the narration prompt leaves
# the signature to the RM, and this is the one she uses in each language.
SIGN = dict({l: f["sign"] for l, f in FRAME.items()},
            Korean="감사합니다.\n" + RM_NAME["Korean"] + "\n" + BANK_NAME["Korean"])

# ── what to say, per dimension ────────────────────────────────────────────
# Plain language. No jargon the client would have to look up: "the value the
# bank will lend against" rather than "lending value", "sold within a day"
# rather than "daily liquidity tier". Slots are filled from finding.numbers.
BODY = {
    "collateral": {
        "English":
            "Your credit facility is currently drawn at {ltv}% of the value the "
            "bank lends against your pledged holdings. The level at which the bank "
            "must ask for money back is {trigger}%. That leaves {room} percentage "
            "points, which is thinner than I am comfortable with — if those "
            "holdings fall in value, the gap closes on its own without anything "
            "being sold.",
        "Traditional Chinese":
            "目前您的信貸額度已動用至抵押資產可貸值的 {ltv}%，而銀行要求補繳的水平為 "
            "{trigger}%，兩者之間只剩 {room} 個百分點。這個空間比我認為穩妥的水準要窄："
            "若抵押資產價格下跌，即使您沒有任何動作，差距也會自行收窄。",
        "Simplified Chinese":
            "目前您的信贷额度已动用至抵押资产可贷值的 {ltv}%，而银行要求补缴的水平为 "
            "{trigger}%，两者之间只剩 {room} 个百分点。这个空间比我认为稳妥的水平要窄："
            "若抵押资产价格下跌，即使您没有任何动作，差距也会自行收窄。",
        "German":
            "Ihre Kreditlinie ist derzeit mit {ltv}% des Werts beansprucht, den die "
            "Bank auf Ihre verpfändeten Positionen beleiht. Nachschusspflichtig "
            "würde es bei {trigger}%. Damit bleiben {room} Prozentpunkte, was "
            "knapper ist, als mir lieb ist: Fallen diese Positionen im Wert, "
            "schliesst sich der Abstand von selbst, ohne dass etwas verkauft wird.",
        "Japanese":
            "現在、担保としてお預かりしている資産の担保評価額に対し、{ltv}% までご融資を"
            "ご利用いただいております。追加担保のご依頼が必要となる水準は {trigger}% で、"
            "残る余裕は {room} ポイントです。これは私が安全と考える水準より薄く、"
            "担保資産の価格が下がれば、何も売却しなくても差は縮まってまいります。",
        "Italian":
            "La Sua linea di credito è attualmente utilizzata al {ltv}% del valore "
            "che la banca finanzia sulle posizioni date in garanzia. Il livello "
            "che farebbe scattare una richiesta di reintegro è {trigger}%. Restano "
            "quindi {room} punti percentuali, un margine più sottile di quanto "
            "riterrei prudente: se quelle posizioni perdono valore, la distanza si "
            "riduce da sola, senza che nulla venga venduto.",
    },
    "funding": {
        "English":
            "You have about {need} falling due in the next twelve months. There is "
            "more than that available in holdings that could be sold within a day — "
            "but those holdings are the security for your credit facility. Selling "
            "them to raise the money would reduce what the bank is willing to lend "
            "you by more than the sale itself brings in, and that is what would "
            "trigger a call for repayment.",
        "Traditional Chinese":
            "未來十二個月內，您有約 {need} 的款項到期。可於一日內變現的資產雖然多於這個"
            "金額，但那些資產同時是您信貸額度的抵押品。若賣出它們來籌措資金，銀行願意"
            "貸給您的額度會減少得比賣出所得更多，反而會觸發補繳的要求。",
        "Simplified Chinese":
            "未来十二个月内，您有约 {need} 的款项到期。可于一日内变现的资产虽然多于这个"
            "金额，但那些资产同时是您信贷额度的抵押品。若卖出它们来筹措资金，银行愿意"
            "贷给您的额度会减少得比卖出所得更多，反而会触发补缴的要求。",
        "German":
            "In den kommenden zwölf Monaten werden rund {need} fällig. Es sind mehr "
            "als das an Positionen vorhanden, die sich binnen eines Tages verkaufen "
            "liessen — nur dienen genau diese Positionen als Sicherheit für Ihre "
            "Kreditlinie. Ein Verkauf würde den Beleihungsrahmen stärker senken, "
            "als der Verkauf einbringt, und genau das löste die Nachschussforderung "
            "aus.",
        "Japanese":
            "今後十二か月以内に、約 {need} のお支払いが予定されております。一日以内に"
            "売却可能な資産はこれを上回っておりますが、その資産はご融資の担保でもござい"
            "ます。資金を作るために売却いたしますと、銀行がご融資できる金額は売却代金"
            "以上に減少し、かえって追加担保のご依頼につながります。",
        "Italian":
            "Nei prossimi dodici mesi Le scadranno circa {need}. Vi sono posizioni "
            "vendibili entro un giorno per un importo superiore, ma sono le stesse "
            "poste a garanzia della Sua linea di credito. Venderle per reperire la "
            "somma ridurrebbe il credito concedibile più di quanto la vendita "
            "stessa produca, ed è proprio questo che farebbe scattare la richiesta "
            "di rientro.",
    },
    "mandate": {
        "English":
            "One part of your portfolio has drifted outside the range we agreed in "
            "your mandate. {what} It is not a loss and nothing has gone wrong; it "
            "simply means the portfolio is now taking a slightly different shape of "
            "risk from the one you signed up to, and I would rather you heard that "
            "from me than found it in a statement.",
        "Traditional Chinese":
            "您投資組合中有一部分已偏離我們在委託協議中約定的區間。{what}這並非虧損，"
            "也沒有出錯；只是組合目前承擔的風險結構，與您當初同意的略有不同。我認為這件事"
            "應該由我告訴您，而不是讓您在對帳單上自己發現。",
        "Simplified Chinese":
            "您投资组合中有一部分已偏离我们在委托协议中约定的区间。{what}这并非亏损，"
            "也没有出错；只是组合目前承担的风险结构，与您当初同意的略有不同。我认为这件事"
            "应该由我告诉您，而不是让您在对账单上自己发现。",
        "German":
            "Ein Teil Ihres Portfolios liegt inzwischen ausserhalb der Bandbreite, "
            "die wir im Mandat vereinbart haben. {what} Es ist kein Verlust und "
            "nichts ist schiefgelaufen; das Portfolio hat lediglich ein etwas "
            "anderes Risikoprofil angenommen als das vereinbarte — und das sollten "
            "Sie von mir hören und nicht im Auszug finden.",
        "Japanese":
            "ご資産の一部が、投資一任契約でお約束した範囲から外れております。{what}"
            "損失が生じているわけでも、手違いがあったわけでもございません。ただ、"
            "ポートフォリオが担うリスクの形が、当初ご同意いただいたものと少し異なって"
            "きております。お取引報告書でお気づきになる前に、私からお伝えすべきと考えました。",
        "Italian":
            "Una parte del Suo portafoglio si è spostata al di fuori della fascia "
            "concordata nel mandato. {what} Non si tratta di una perdita né di un "
            "errore: semplicemente il portafoglio ha assunto un profilo di rischio "
            "un po' diverso da quello che aveva sottoscritto, e preferisco che lo "
            "sappia da me anziché trovarlo in un estratto conto.",
    },
    "concentration": {
        "English":
            "Looking across everything you hold with us, {name} accounts for about "
            "{share}% of your total wealth — roughly {usd}. Part of that sits inside "
            "structured products rather than being held directly, so it does not "
            "show as one line on any single statement. It is worth being deliberate "
            "about a position that size rather than arriving at it by accident.",
        "Traditional Chinese":
            "綜觀您在本行的全部持倉，{name} 約佔您總資產的 {share}%，金額約 {usd}。其中"
            "一部分是透過結構性產品持有，而非直接持股，因此不會在任何單一對帳單上顯示為"
            "一個項目。這樣規模的部位，值得是刻意的決定，而不是不知不覺累積而成。",
        "Simplified Chinese":
            "综观您在本行的全部持仓，{name} 约占您总资产的 {share}%，金额约 {usd}。其中"
            "一部分是通过结构性产品持有，而非直接持股，因此不会在任何单一对账单上显示为"
            "一个项目。这样规模的仓位，值得是刻意的决定，而不是不知不觉累积而成。",
        "German":
            "Über alle Ihre Positionen bei uns hinweg entfällt auf {name} rund "
            "{share}% Ihres Gesamtvermögens, etwa {usd}. Ein Teil davon steckt in "
            "strukturierten Produkten statt in einem Direktbestand und erscheint "
            "deshalb auf keinem einzelnen Auszug als eine Position. Eine Grösse "
            "dieser Art sollte eine bewusste Entscheidung sein und nicht zufällig "
            "entstehen.",
        "Japanese":
            "当行でお預かりしている資産全体で見ますと、{name} はご資産の約 {share}%、"
            "金額にして約 {usd} を占めております。その一部は直接保有ではなく仕組商品を"
            "通じた保有のため、個々のご報告書には一項目として現れません。この規模の"
            "エクスポージャーは、結果としてそうなるのではなく、意図してお決めいただく"
            "べきものと存じます。",
        "Italian":
            "Considerando l'insieme di ciò che detiene con noi, {name} rappresenta "
            "circa il {share}% del Suo patrimonio complessivo, all'incirca {usd}. "
            "Una parte è detenuta tramite prodotti strutturati anziché in via "
            "diretta e quindi non compare come singola riga in nessun estratto. Una "
            "posizione di questa dimensione merita di essere una scelta "
            "consapevole, non il risultato di una somma casuale.",
    },
    "purpose_fit": {
        "English":
            "About {share}% of your wealth is invested in bonds that mature after "
            "{year}, which is the point you have told us you need the money by. At "
            "today's prices those holdings are {loss} below what was paid for them. "
            "Holding to maturity does recover the money — but it recovers it later "
            "than you need it, and that is the part worth talking about.",
        "Traditional Chinese":
            "您約 {share}% 的資產投資於 {year} 年之後才到期的債券，而 {year} 年正是您"
            "告知我們需要動用這筆資金的時點。以今日價格計算，這些持倉較買入成本低約 "
            "{loss}。持有至到期確實能拿回本金，但拿回的時間會晚於您需要用錢的時候——"
            "這才是值得談的地方。",
        "Simplified Chinese":
            "您约 {share}% 的资产投资于 {year} 年之后才到期的债券，而 {year} 年正是您"
            "告知我们需要动用这笔资金的时点。以今日价格计算，这些持仓较买入成本低约 "
            "{loss}。持有至到期确实能拿回本金，但拿回的时间会晚于您需要用钱的时候——"
            "这才是值得谈的地方。",
        "German":
            "Rund {share}% Ihres Vermögens stecken in Anleihen, die nach {year} "
            "fällig werden — dem Zeitpunkt, zu dem Sie das Geld nach eigener Angabe "
            "benötigen. Zu heutigen Kursen liegen diese Positionen {loss} unter dem "
            "Einstand. Bis zur Fälligkeit zu halten holt das Geld zurück, aber "
            "später, als Sie es brauchen — und genau darüber sollten wir sprechen.",
        "Japanese":
            "ご資産の約 {share}% は、{year} 年より後に満期を迎える債券で運用されており"
            "ます。{year} 年は、資金が必要になるとお聞きしている時期です。現在の価格では、"
            "これらの保有は取得価格を約 {loss} 下回っております。満期まで保有すれば資金は"
            "戻りますが、戻る時期がご入用の時期より後になります。その点をご相談したく存じます。",
        "Italian":
            "Circa il {share}% del Suo patrimonio è investito in obbligazioni con "
            "scadenza successiva al {year}, l'orizzonte entro il quale ci ha "
            "indicato di aver bisogno di quelle somme. Ai prezzi odierni tali "
            "posizioni valgono {loss} in meno di quanto pagato. Portarle a scadenza "
            "recupera il capitale, ma lo recupera più tardi di quando Le serve: è "
            "questo il punto da discutere.",
    },
    "life_event": {
        "English":
            "I have {what} on your file, due from {when}. At around {share}% of "
            "everything you hold, it is large enough that it should shape the "
            "portfolio rather than be met out of it at the last minute. I would like "
            "to check we are holding the right things, in the right form, for that "
            "date.",
        "Traditional Chinese":
            "您的檔案中記錄了「{what}」，自 {when} 起到期。這筆金額約佔您全部資產的 "
            "{share}%，規模足以影響投資組合的安排，而不宜臨到期才設法應付。我希望能與您"
            "確認：為了這個時點，我們持有的資產種類與形式是否恰當。",
        "Simplified Chinese":
            "您的档案中记录了“{what}”，自 {when} 起到期。这笔金额约占您全部资产的 "
            "{share}%，规模足以影响投资组合的安排，而不宜临到期才设法应付。我希望能与您"
            "确认：为了这个时点，我们持有的资产种类与形式是否恰当。",
        "German":
            "In Ihren Unterlagen ist {what} vermerkt, fällig ab {when}. Mit rund "
            "{share}% Ihres Gesamtvermögens ist der Betrag gross genug, dass er das "
            "Portfolio prägen sollte, statt kurzfristig daraus bedient zu werden. "
            "Ich möchte gern prüfen, ob wir für diesen Termin das Richtige in der "
            "richtigen Form halten.",
        "Japanese":
            "お客さまの記録に「{what}」を確認しております。{when} よりお支払いの予定です。"
            "ご資産全体の約 {share}% にあたる規模ですので、直前に工面するのではなく、"
            "ポートフォリオの組み立て自体に反映すべき金額と存じます。その時期に向けて、"
            "適切な資産を適切な形で保有できているか、ご一緒に確認させてください。",
        "Italian":
            "Nella Sua posizione risulta {what}, con scadenza a partire dal {when}. "
            "Con circa il {share}% di quanto detiene, è un importo abbastanza "
            "rilevante da dover orientare il portafoglio, anziché essere reperito "
            "all'ultimo momento. Vorrei verificare che stiamo detenendo le cose "
            "giuste, nella forma giusta, per quella data.",
    },
    "tax": {
        "English":
            "Some of your holdings are currently worth less than you paid for them, "
            "and some are worth more. Where you are taxed, losses that are actually "
            "realised can be set against gains — so there may be something to plan "
            "here. I would want our wealth planning colleagues to look at it with "
            "us before anything is sold; this is a conversation, not a "
            "recommendation.",
        "Traditional Chinese":
            "您目前部分持倉的市值低於買入成本，另有部分高於成本。在您的稅務居民地，"
            "已實現的虧損可用以沖抵已實現的收益，因此這裡可能有規劃空間。在賣出任何"
            "資產之前，我會希望財富規劃同事與我們一同檢視。這是一次討論，而非建議。",
        "Simplified Chinese":
            "您目前部分持仓的市值低于买入成本，另有部分高于成本。在您的税务居民地，"
            "已实现的亏损可用以冲抵已实现的收益，因此这里可能有规划空间。在卖出任何"
            "资产之前，我会希望财富规划同事与我们一同检视。这是一次讨论，而非建议。",
        "German":
            "Ein Teil Ihrer Positionen liegt derzeit unter dem Einstand, ein anderer "
            "darüber. In Ihrem Steuerdomizil lassen sich realisierte Verluste gegen "
            "Gewinne verrechnen, hier liesse sich also möglicherweise etwas "
            "gestalten. Bevor etwas verkauft wird, möchte ich unsere Kolleginnen und "
            "Kollegen aus der Nachfolge- und Steuerplanung hinzuziehen. Das ist ein "
            "Gesprächsangebot, keine Empfehlung.",
        "Japanese":
            "現在、取得価格を下回っている保有と、上回っている保有がございます。お客さまの"
            "課税地では、実現した損失を実現益と相殺できるため、検討の余地があるかもしれ"
            "ません。売却の前に、ウェルスプランニングの担当者を交えて一緒に確認したいと"
            "考えております。これはご提案ではなく、ご相談です。",
        "Italian":
            "Alcune delle Sue posizioni valgono oggi meno di quanto pagato, altre di "
            "più. Nella Sua giurisdizione fiscale le minusvalenze effettivamente "
            "realizzate possono essere compensate con le plusvalenze: c'è quindi "
            "forse qualcosa da pianificare. Prima di vendere alcunché vorrei "
            "coinvolgere i colleghi della pianificazione patrimoniale. È un "
            "confronto, non una raccomandazione.",
    },
    "data_quality": {
        "English":
            "One of your larger holdings is still being valued at a price dated "
            "{marked}. For private and unlisted investments a lag is normal, but it "
            "is a big enough share of your total that I would not want you making a "
            "decision on a figure that old. I am asking for a current valuation.",
        "Traditional Chinese":
            "您其中一項較大的持倉，目前仍以 {marked} 的價格計值。私募與未上市投資的估值"
            "落後屬正常現象，但這項持倉佔您總資產的比重不小，我不希望您依據這麼舊的數字"
            "做決定。我已在索取最新估值。",
        "Simplified Chinese":
            "您其中一项较大的持仓，目前仍以 {marked} 的价格计值。私募与未上市投资的估值"
            "落后属正常现象，但这项持仓占您总资产的比重不小，我不希望您依据这么旧的数字"
            "做决定。我已在索取最新估值。",
        "German":
            "Eine Ihrer grösseren Positionen wird noch mit einem Kurs vom {marked} "
            "bewertet. Bei privaten und nicht kotierten Anlagen ist eine Verzögerung "
            "normal, doch der Anteil am Gesamtvermögen ist gross genug, dass Sie "
            "keine Entscheidung auf einer so alten Zahl treffen sollten. Ich fordere "
            "eine aktuelle Bewertung an.",
        "Japanese":
            "お預かりしている大きめの保有のうち一件が、{marked} 時点の価格のまま評価"
            "されております。未公開・非上場投資では評価の遅れは通常のことですが、ご資産"
            "全体に占める割合が大きいため、これほど古い数値をもとにご判断いただくのは"
            "避けたいと考えております。最新の評価を取り寄せております。",
        "Italian":
            "Una delle Sue posizioni più rilevanti è ancora valorizzata a un prezzo "
            "datato {marked}. Per gli investimenti privati e non quotati un ritardo "
            "è normale, ma il peso sul totale è tale che non vorrei che prendesse "
            "decisioni su un dato così vecchio. Sto richiedendo una valutazione "
            "aggiornata.",
    },
}

# What we suggest, per dimension. Deliberately softer than `finding.action`,
# which is written as an instruction to the RM.
SUGGEST = {
    "collateral": {
        "English": "let us look at the facility together before any sale or "
                   "drawdown, so nothing is done that narrows that gap further.",
        "Traditional Chinese": "在進行任何賣出或動用額度之前，我們先一起檢視這筆信貸安排，"
                              "避免任何進一步壓縮空間的動作。",
        "Simplified Chinese": "在进行任何卖出或动用额度之前，我们先一起检视这笔信贷安排，"
                             "避免任何进一步压缩空间的动作。",
        "German": "dass wir die Kreditlinie gemeinsam ansehen, bevor verkauft oder "
                  "gezogen wird, damit der Abstand nicht weiter schrumpft.",
        "Japanese": "売却やご融資のお引き出しの前に、まずご一緒にこの与信の状況を確認する"
                   "ことです。余裕をこれ以上狭める動きを避けるためです。",
        "Italian": "di esaminare insieme la linea di credito prima di qualsiasi "
                   "vendita o utilizzo, così da non ridurre ulteriormente quel margine.",
    },
    "funding": {
        "English": "we fund this from outside the pledged portfolio, or reduce the "
                   "facility first. Selling the collateral is the one route that "
                   "creates the problem.",
        "Traditional Chinese": "以抵押組合以外的資金支應這筆款項，或先行降低信貸餘額。"
                              "賣出抵押品，正是唯一會製造問題的做法。",
        "Simplified Chinese": "以抵押组合以外的资金支应这笔款项，或先行降低信贷余额。"
                             "卖出抵押品，正是唯一会制造问题的做法。",
        "German": "dies ausserhalb des verpfändeten Depots zu finanzieren oder die "
                  "Kreditlinie zuerst zurückzuführen. Der Verkauf der Sicherheiten "
                  "ist der eine Weg, der das Problem erst erzeugt.",
        "Japanese": "担保に入っていない資産からご用立てするか、先にご融資を圧縮することです。"
                   "担保資産の売却こそが、問題を生む唯一の経路です。",
        "Italian": "di finanziare l'importo al di fuori del portafoglio dato in "
                   "garanzia, oppure di ridurre prima la linea. Vendere il collaterale "
                   "è l'unica strada che crea il problema.",
    },
    "mandate": {
        "English": "we either bring it back inside the range, or you tell me you are "
                   "comfortable as it stands and I record that on your file. Both are "
                   "fine; leaving it undecided is not.",
        "Traditional Chinese": "要麼我們把它調整回約定區間，要麼由您告訴我維持現狀即可，"
                              "我會將此記錄於您的檔案中。兩者皆可，唯獨懸而未決不宜。",
        "Simplified Chinese": "要么我们把它调整回约定区间，要么由您告诉我维持现状即可，"
                             "我会将此记录于您的档案中。两者皆可，唯独悬而未决不宜。",
        "German": "dass wir entweder in die Bandbreite zurückkehren oder Sie mir "
                  "sagen, dass es so bleiben soll — dann halte ich das in Ihren "
                  "Unterlagen fest. Beides ist in Ordnung; offen zu lassen nicht.",
        "Japanese": "約定の範囲内に戻すか、あるいは現状のままで差し支えないとお申しつけ"
                   "いただき、その旨を記録として残すか、いずれかです。どちらでも構いませんが、"
                   "未決のままにしておくことだけは避けたく存じます。",
        "Italian": "di riportarla dentro la fascia, oppure che Lei mi dica di essere "
                   "a Suo agio così com'è: in tal caso lo annoto nella Sua posizione. "
                   "Entrambe vanno bene; lasciarla in sospeso no.",
    },
    "concentration": {
        "English": "we look at the total in one place, and you decide whether that is "
                   "the position you want. If it is, nothing needs to change.",
        "Traditional Chinese": "我們把這個總額放在同一張表上一起看，由您決定這是否是您"
                              "想要的部位。若是，則無需任何調整。",
        "Simplified Chinese": "我们把这个总额放在同一张表上一起看，由您决定这是否是您"
                             "想要的仓位。若是，则无需任何调整。",
        "German": "dass wir die Summe einmal an einem Ort betrachten und Sie "
                  "entscheiden, ob das die gewünschte Position ist. Wenn ja, muss "
                  "sich nichts ändern.",
        "Japanese": "合計額を一枚にまとめてご覧いただき、これがお望みのエクスポージャー"
                   "かどうかをご判断いただくことです。そうであれば、変更は不要です。",
        "Italian": "di guardare il totale in un unico prospetto e che sia Lei a "
                   "decidere se è la posizione che desidera. Se lo è, non serve "
                   "cambiare nulla.",
    },
    "purpose_fit": {
        "English": "we shorten part of that ladder so the money arrives when you need "
                   "it, rather than waiting for a recovery on someone else's timetable.",
        "Traditional Chinese": "把其中一部分到期結構縮短，讓資金在您需要的時候到位，"
                              "而不是等待一個不由您決定時點的價格回升。",
        "Simplified Chinese": "把其中一部分到期结构缩短，让资金在您需要的时候到位，"
                             "而不是等待一个不由您决定时点的价格回升。",
        "German": "einen Teil dieser Fälligkeitsleiter zu verkürzen, damit das Geld "
                  "dann da ist, wenn Sie es brauchen, statt auf eine Erholung nach "
                  "fremdem Zeitplan zu warten.",
        "Japanese": "この満期の階段の一部を短くし、他人の時間軸での値戻りを待つのではなく、"
                   "ご必要な時期に資金が整うようにすることです。",
        "Italian": "di accorciare una parte di quella scala di scadenze, così che il "
                   "denaro arrivi quando Le serve, invece di attendere un recupero "
                   "secondo i tempi di altri.",
    },
    "life_event": {
        "English": "we set aside how this will be paid for now, while there is still "
                   "time to do it calmly.",
        "Traditional Chinese": "趁現在還有從容安排的時間，先把這筆支出的來源規劃好。",
        "Simplified Chinese": "趁现在还有从容安排的时间，先把这笔支出的来源规划好。",
        "German": "jetzt festzulegen, woraus das bezahlt wird, solange dafür noch in "
                  "Ruhe Zeit ist.",
        "Japanese": "落ち着いて準備できる時間があるうちに、この支払いの原資を今のうちに"
                   "決めておくことです。",
        "Italian": "di stabilire fin d'ora con quali risorse verrà pagato, finché "
                   "c'è ancora tempo per farlo con calma.",
    },
    "tax": {
        "English": "we put the numbers in front of wealth planning before we act on "
                   "any of it.",
        "Traditional Chinese": "在採取任何行動之前，先把這些數字交給財富規劃團隊過目。",
        "Simplified Chinese": "在采取任何行动之前，先把这些数字交给财富规划团队过目。",
        "German": "die Zahlen der Nachfolge- und Steuerplanung vorzulegen, bevor wir "
                  "irgendetwas davon umsetzen.",
        "Japanese": "何らかの実行に移す前に、これらの数字をウェルスプランニングに"
                   "確認してもらうことです。",
        "Italian": "di sottoporre i numeri alla pianificazione patrimoniale prima di "
                   "agire in qualsiasi direzione.",
    },
    "data_quality": {
        "English": "we get the valuation refreshed before you rely on the total for "
                   "anything.",
        "Traditional Chinese": "在您憑總額作任何判斷之前，先把這項估值更新。",
        "Simplified Chinese": "在您凭总额作任何判断之前，先把这项估值更新。",
        "German": "die Bewertung zu aktualisieren, bevor Sie sich für irgendetwas auf "
                  "die Gesamtsumme stützen.",
        "Japanese": "合計額を何かの判断に用いられる前に、この評価を更新することです。",
        "Italian": "di aggiornare la valutazione prima che Lei si basi sul totale "
                   "per qualsiasi decisione.",
    },
}


# ── slot filling ──────────────────────────────────────────────────────────
# A figure written the way the reader counts. "USD 7.7m" is not how anyone
# reads a number in Chinese or Japanese — 萬 and 億 are the units, and a note
# that ignores that is a translated note rather than a note in the language.
CJK_UNITS = {
    "Traditional Chinese": ("美元", "萬", "億", False),
    "Simplified Chinese":  ("美元", "万", "亿", False),
    "Japanese":            ("米ドル", "万", "億", True),
}


def _cjk_amount(v, lang):
    ccy, wan, yi, suffix_ccy = CJK_UNITS[lang]
    if v >= 1e8:
        n = v / 1e8
        num = ("%.2f" % n).rstrip("0").rstrip(".")
        unit = yi
    elif v >= 1e4:
        n = v / 1e4
        num = "{:,.0f}".format(n) if n >= 100 else ("%.1f" % n).rstrip("0").rstrip(".")
        unit = wan
    else:
        return "%s %d" % (ccy, round(v))
    # Chinese puts the currency last, Japanese puts it last too; both read
    # "<number><unit><currency>"
    return "%s%s%s" % (num, unit, ccy)


def _usd(v, lang="English"):
    v = abs(float(v))
    if lang in CJK_UNITS:
        return _cjk_amount(v, lang)
    if v >= 1e6:
        return "USD %.1fm" % (v / 1e6)
    if v >= 1e3:
        return "USD %dk" % round(v / 1e3)
    return "USD %d" % round(v)


# The mandate clause, per shape of breach, in each language. The English
# headline cannot be reused here: dropping "Commodities is 1.0 points above its
# BAL band in PF-0018" into the middle of a Chinese paragraph is not a
# translated note, it is an English note with the greeting changed.
MANDATE_CLAUSE = {
    "over": {
        "English": "{asset} now sits at {weight}% of that portfolio, against an "
                   "agreed ceiling of {limit}%.",
        "Traditional Chinese": "{asset} 目前佔該組合的 {weight}%，而約定上限為 {limit}%。",
        "Simplified Chinese": "{asset} 目前占该组合的 {weight}%，而约定上限为 {limit}%。",
        "German": "{asset} liegt derzeit bei {weight}% dieses Portfolios, "
                  "gegenüber einer vereinbarten Obergrenze von {limit}%.",
        "Japanese": "{asset} は現在、当該ポートフォリオの {weight}% を占めており、"
                   "お約束の上限は {limit}% です。",
        "Italian": "{asset} rappresenta ora il {weight}% di quel portafoglio, a "
                   "fronte di un limite concordato del {limit}%.",
    },
    "under": {
        "English": "{asset} now sits at {weight}% of that portfolio, against an "
                   "agreed floor of {limit}%.",
        "Traditional Chinese": "{asset} 目前僅佔該組合的 {weight}%，而約定下限為 {limit}%。",
        "Simplified Chinese": "{asset} 目前仅占该组合的 {weight}%，而约定下限为 {limit}%。",
        "German": "{asset} liegt derzeit bei {weight}% dieses Portfolios, "
                  "gegenüber einer vereinbarten Untergrenze von {limit}%.",
        "Japanese": "{asset} は現在、当該ポートフォリオの {weight}% にとどまっており、"
                   "お約束の下限は {limit}% です。",
        "Italian": "{asset} rappresenta ora solo il {weight}% di quel portafoglio, "
                   "a fronte di una soglia minima concordata del {limit}%.",
    },
    "single": {
        "English": "{asset} alone is {weight}% of that portfolio, where the mandate "
                   "caps any one position at {limit}%.",
        "Traditional Chinese": "單是 {asset} 一項就佔該組合的 {weight}%，而委託協議規定"
                              "任何單一持倉不得超過 {limit}%。",
        "Simplified Chinese": "单是 {asset} 一项就占该组合的 {weight}%，而委托协议规定"
                             "任何单一持仓不得超过 {limit}%。",
        "German": "Allein {asset} macht {weight}% dieses Portfolios aus, während das "
                  "Mandat jede Einzelposition auf {limit}% begrenzt.",
        "Japanese": "{asset} 一銘柄で当該ポートフォリオの {weight}% を占めており、"
                   "契約上、単一銘柄の上限は {limit}% です。",
        "Italian": "La sola {asset} pesa per il {weight}% di quel portafoglio, "
                   "mentre il mandato limita ogni singola posizione al {limit}%.",
    },
    "excluded": {
        "English": "{asset} is {weight}% of that portfolio and appears on the "
                   "exclusion list your mandate is built around.",
        "Traditional Chinese": "{asset} 佔該組合的 {weight}%，且列於您委託協議所依據的"
                              "排除名單之中。",
        "Simplified Chinese": "{asset} 占该组合的 {weight}%，且列于您委托协议所依据的"
                             "排除名单之中。",
        "German": "{asset} macht {weight}% dieses Portfolios aus und steht auf der "
                  "Ausschlussliste, auf der Ihr Mandat aufbaut.",
        "Japanese": "{asset} は当該ポートフォリオの {weight}% を占めており、"
                   "ご契約の前提となる除外リストに掲載されている銘柄です。",
        "Italian": "{asset} pesa per il {weight}% di quel portafoglio e figura "
                   "nell'elenco di esclusione su cui è costruito il Suo mandato.",
    },
    "excluded_many": {
        "English": "{asset} together make up {weight}% of that portfolio, and each "
                   "appears on the exclusion list your mandate is built around.",
        "Traditional Chinese": "{asset} 合共佔該組合的 {weight}%，且均列於您委託協議所依據的"
                              "排除名單之中。",
        "Simplified Chinese": "{asset} 合共占该组合的 {weight}%，且均列于您委托协议所依据的"
                             "排除名单之中。",
        "German": "{asset} machen zusammen {weight}% dieses Portfolios aus und stehen "
                  "alle auf der Ausschlussliste, auf der Ihr Mandat aufbaut.",
        "Japanese": "{asset} は合わせて当該ポートフォリオの {weight}% を占めており、"
                   "いずれもご契約の前提となる除外リストに掲載されている銘柄です。",
        "Italian": "{asset} pesano insieme per il {weight}% di quel portafoglio e "
                   "figurano tutti nell'elenco di esclusione su cui è costruito il Suo "
                   "mandato.",
    },
}

# "A, B and C" as each language writes a list of names.
LIST_JOIN = {
    "English": (", ", " and "),
    "Traditional Chinese": ("、", " 及 "),
    "Simplified Chinese": ("、", " 和 "),
    "German": (", ", " und "),
    "Japanese": ("、", "、"),
    "Italian": (", ", " e "),
}


def _join(names, lang):
    sep, last = LIST_JOIN[lang]
    return names[0] if len(names) == 1 else sep.join(names[:-1]) + last + names[-1]


# Asset-class names come from the data in English. Leaving "Commodities" in the
# middle of a German sentence is the same mistake as leaving the whole headline
# there, only smaller. Instrument names are proper nouns and stay as they are.
ASSET_CLASS = {
    "Cash and Equivalents": {
        "Traditional Chinese": "現金及等價物", "Simplified Chinese": "现金及等价物",
        "German": "Liquidität", "Japanese": "現金および現金同等物",
        "Italian": "Liquidità"},
    "Fixed Income": {
        "Traditional Chinese": "固定收益", "Simplified Chinese": "固定收益",
        "German": "Anleihen", "Japanese": "債券", "Italian": "Obbligazioni"},
    "Equity": {
        "Traditional Chinese": "股票", "Simplified Chinese": "股票",
        "German": "Aktien", "Japanese": "株式", "Italian": "Azioni"},
    "Alternatives": {
        "Traditional Chinese": "另類投資", "Simplified Chinese": "另类投资",
        "German": "Alternative Anlagen", "Japanese": "オルタナティブ投資",
        "Italian": "Investimenti alternativi"},
    "Commodities": {
        "Traditional Chinese": "商品", "Simplified Chinese": "商品",
        "German": "Rohstoffe", "Japanese": "コモディティ", "Italian": "Materie prime"},
    "Structured Products": {
        "Traditional Chinese": "結構性產品", "Simplified Chinese": "结构性产品",
        "German": "Strukturierte Produkte", "Japanese": "仕組商品",
        "Italian": "Prodotti strutturati"},
}


def _mandate_clause(f, lang):
    n, head = f.numbers, f.headline
    asset = head.split(" is ")[0] if " is " in head else head.split(" breaches ")[0]
    asset = ASSET_CLASS.get(asset, {}).get(lang, asset)
    w = "%.1f" % n.get("weight_pct", 0)
    if f.id.startswith("EXC-"):
        held = [h["instrument"] for h in n.get("holdings", [])]
        shape, limit = "excluded" if len(held) <= 1 else "excluded_many", None
        if held:
            asset = _join(held, lang)          # proper nouns, never translated
    elif f.id.startswith("LIM-"):
        shape, limit = "single", "%g" % n.get("limit_pct", 0)
    elif " below " in head:
        shape, limit = "under", "%g" % n.get("min_pct", 0)
    else:
        shape, limit = "over", "%g" % n.get("max_pct", 0)
    return MANDATE_CLAUSE[shape][lang].format(asset=asset, weight=w, limit=limit)


def _slots(f, lang):
    """Every slot any body might need, from the finding's own numbers."""
    n = f.numbers
    s = {}
    if f.dimension == "collateral":
        s["ltv"] = "%.1f" % n.get("ltv_pct", 0)
        s["trigger"] = "%g" % n.get("trigger_pct", 0)
        s["room"] = "%.1f" % n.get("headroom_pp", 0)
    elif f.dimension == "funding":
        s["need"] = _usd(n.get("need_usd", 0), lang)
    elif f.dimension == "mandate":
        s["what"] = _mandate_clause(f, lang)
    elif f.dimension == "concentration":
        s["name"] = f.headline.split(" is ")[0]
        s["share"] = "%.0f" % n.get("weight_pct", 0)
        s["usd"] = _usd(n.get("usd", 0), lang)
    elif f.dimension == "purpose_fit":
        s["share"] = "%.0f" % n.get("sleeve_pct", 0)
        s["year"] = str(n.get("horizon_end", ""))
        s["loss"] = _usd(n.get("unrealised_usd", 0), lang)
    elif f.dimension == "life_event":
        s["what"] = f.headline.split(" — ")[0]
        s["when"] = n.get("due_from", "")
        s["share"] = "%.0f" % n.get("share_pct", 0)
    elif f.dimension == "data_quality":
        s["marked"] = n.get("marked", "")
    return s


def note_for(finding, language):
    """The whole note, in one language, or None if we cannot write it."""
    frame = FRAME.get(language)
    body = BODY.get(finding.dimension, {}).get(language)
    suggest = SUGGEST.get(finding.dimension, {}).get(language)
    if not (frame and body and suggest):
        return None
    try:
        body = body.format(**_slots(finding, language))
    except (KeyError, IndexError, ValueError):
        return None
    lead_in = {"English": "What I would suggest is that ",
               "Traditional Chinese": "我的建議是：",
               "Simplified Chinese": "我的建议是：",
               "German": "Mein Vorschlag wäre, ",
               "Japanese": "私の提案は、",
               "Italian": "Il mio suggerimento è "}[language]
    return "\n\n".join([frame["greeting"], frame["opening"], body,
                        lead_in + suggest, frame["close"], frame["sign"]])


def build(book, findings):
    """{finding id -> {language tag -> note}} for every finding we can write.

    Always English. Plus the client's reporting language when we have frames
    for it — which is all six languages this book actually uses."""
    out = {}
    for f in findings:
        langs = ["English"]
        lang = (book.C.get(f.client_id, {}) or {}).get("reporting_language", "")
        if lang and lang != "English" and lang in FRAME:
            langs.append(lang)
        got = {}
        for l in langs:
            text = note_for(f, l)
            if text:
                got[l] = {"tag": TAGS[l], "text": text}
        if got:
            out[f.id] = got
    return out
