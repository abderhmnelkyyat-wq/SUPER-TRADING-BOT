# ربط الأخبار والبوتات الخارجية — SUPER TRADING BOT 1.1

## ما الذي أُضيف؟

- مصادر RSS وAtom عبر HTTPS.
- استقبال محتوى من أي بوت أو خدمة خارجية عبر Webhook موحّد.
- استقبال منشورات القنوات العامة عبر Telegram Bot API فقط؛ تُهمل الرسائل الخاصة ورسائل المجموعات منعًا لمشاركة معلومات خاصة مع جميع العملاء.
- توحيد المحتوى في سجل معلومات واحد مع إزالة التكرار وتسجيل المصدر ووقت النشر والاستلام.
- واجهة عميل لعرض الأخبار والرسائل الواردة.
- مساعد محادثة نصي اختياري يستخدم ملخص أخبار المصادر المفعّلة وإحصاءات الصفقات الخاصة بالعميل الحالي فقط، إذا ضُبط مزود نموذج متوافق.
- صلاحيات إنشاء المصادر وإدارتها محصورة في API المالك.

## حدود الأمان

1. الأخبار ورسائل البوتات مدخلات خارجية غير موثقة. لا تُعامل كتوصية مالية أو أمر BUY/SELL.
2. لا يستطيع هذا التكامل فتح صفقة أو تعديل وقف خسارة أو تجاوز Risk Manager.
3. مساعد المحادثة يرسل ملخصًا محدودًا من الصفقات الخاصة بالعميل الحالي وآخر الأخبار المفعّلة فقط إلى مزود النموذج الذي يضبطه مالك الخادم. لا يُرسل البريد أو كلمات مرور الوسيط أو رموز الترخيص. يجب اعتبار الأخبار محتوى غير موثوق، لا تعليمات للنموذج.
4. المحادثة لا تملك أدوات تداول ولا تنفذ أوامر أو تعدل إعدادات الحساب. لا يتم إرسال أوامر BUY/SELL من المساعد إلى MT5.
5. RSS يقبل HTTPS فقط، ويمنع التحويلات ويُرفض عند توجيهه إلى عناوين شبكات خاصة/محلية. استخدم مصادر موثوقة تملك إذن الوصول إليها.
6. استخدم خلاصات RSS/Atom الرسمية أو واجهات API المرخّصة؛ لا تعتمد على كشط صفحات محمية أو تجاوز شروط المواقع.
7. لا ترسل مفاتيح API أو كلمات مرور الوسطاء إلى Webhook. استخدم رمز التكامل الذي يظهر مرة واحدة عند الإنشاء.
8. لا يستطيع Telegram bot قراءة محادثات بوتات أخرى تلقائيًا. سيستقبل فقط منشورات القنوات العامة التي يرسلها Telegram إلى webhook الخاص به؛ الرسائل الخاصة ورسائل المجموعات يتم تجاهلها في هذه النسخة. المحتوى المقبول يظهر لجميع العملاء النشطين، لذلك لا تربط مصدرًا يحمل معلومات خاصة.

## إنشاء مصدر RSS بواسطة API المالك

بعد تسجيل دخول المالك، احتفظ برمز الجلسة في متغير بيئة محلي باسم `OWNER_TOKEN`، ثم نفّذ:

```bash
curl -X POST "$PUBLIC_APP_URL/api/owner/integrations/sources" \
  -H "Authorization: Bearer $OWNER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Official Market Feed","kind":"rss","url":"https://example.com/feed.xml"}'
```

استبدل الرابط بموجز HTTPS رسمي وموثوق. بعد إنشاء المصدر، يمكن جلبه فورًا:

```bash
curl -X POST "$PUBLIC_APP_URL/api/owner/integrations/sources/SOURCE_ID/poll" \
  -H "Authorization: Bearer $OWNER_TOKEN"
```

ولعرض قائمة المصادر:

```bash
curl "$PUBLIC_APP_URL/api/owner/integrations/sources" \
  -H "Authorization: Bearer $OWNER_TOKEN"
```

## ربط بوت خارجي عبر Webhook

أنشئ مصدرًا من نوع `webhook`:

```bash
curl -X POST "$PUBLIC_APP_URL/api/owner/integrations/sources" \
  -H "Authorization: Bearer $OWNER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"My Signal Bot","kind":"webhook"}'
```

سيظهر `secret_once` مرة واحدة فقط. خزّنه في إعدادات البوت الخارجي، ولا تضعه داخل JavaScript للمتصفح أو مستودع Git.

صيغة الإرسال:

```bash
curl -X POST "$PUBLIC_APP_URL/api/integrations/webhook/SOURCE_ID" \
  -H "X-Integration-Token: YOUR_SECRET_ONCE" \
  -H "Content-Type: application/json" \
  -d '{
    "external_id":"event-0001",
    "item_type":"market_event",
    "title":"Market update",
    "summary":"A normalized, factual summary from the external bot.",
    "url":"https://example.com/story",
    "published_at":"2026-11-16T12:00:00Z",
    "symbols":["EURUSD","XAUUSD"]
  }'
```

الأنواع المسموحة: `news` أو `market_event` أو `bot_message`. لا توجد قيمة نوع تنشئ أمر تداول.

## ربط Telegram Bot

أنشئ مصدرًا من نوع `telegram`، ثم استخدم `webhook_url` و`secret_once` اللذين يرجعان مرة واحدة عند الإنشاء لإعداد webhook عبر Telegram Bot API. أرسل السر في الحقل `secret_token` عند `setWebhook`؛ سيضع Telegram قيمته في ترويسة `X-Telegram-Bot-Api-Secret-Token`.

يجب أن يكون البوت ملكك أو لديك صلاحية إدارته، وأن يكون عضوًا/مسؤولًا في القناة العامة. لا تحاول قراءة رسائل بوتات أخرى أو قنوات لا يملك البوت حق الوصول إليها.

## مساعد التداول الذكي (النص)

توجد واجهة محادثة نصية داخل صفحة الأخبار. تتطلب موافقة العميل قبل كل إرسال؛ عند الموافقة، يُرسل السؤال وسياق المحادثة وملخص آخر 8 صفقات مغلقة وإشارات العميل وآخر 10 أخبار إلى مزود النموذج. لا يُرسل البريد أو كلمات مرور الوسيط أو رموز الترخيص. لا تُخزن المحادثات على الخادم في هذه المرحلة. تستخدم فقط عند ضبط مزود يدعم تنسيق OpenAI Chat Completions عبر HTTPS. لا يحتوي الإصدار على مفتاح API مضمّن؛ اترك القيم فارغة لتعطيل المساعد، ثم ضع إعدادات المزود في بيئة الخادم الخاصة (ولا تضع المفتاح في ملفات الواجهة أو Git):

```dotenv
AI_CHAT_API_URL=https://YOUR_PROVIDER.example/v1/chat/completions
AI_CHAT_API_KEY=SET_ON_SERVER_ONLY
AI_CHAT_MODEL=YOUR_PROVIDER_MODEL_ID
```

بعد إعادة تشغيل API، يظهر المساعد متاحًا للعملاء النشطين. يمكن استبدال المزود بتعديل هذه القيم دون تغيير واجهة التطبيق، بشرط توافقه مع تنسيق Chat Completions. يتلقى النموذج ملخصًا لآخر 8 صفقات مغلقة وإشارات العميل وآخر 10 أخبار؛ لا يتلقى بيانات دخول الوسيط. لا توجد محادثة صوتية في هذا الإصدار.

## تشغيل جامع RSS دوريًا

ينفّذ السكربت دورة واحدة على جميع المصادر المفعلة:

```bash
cd backend
python scripts/poll_news.py
```

في خادم Linux، أضف Cron كل خمس دقائق بعد التأكد من البيئة والنسخ الاحتياطية:

```cron
*/5 * * * * cd /opt/super-trading-bot/backend && /opt/super-trading-bot/.venv/bin/python scripts/poll_news.py >> /var/log/superbot-news.log 2>&1
```

لا تشغّل أكثر من جامع متزامن على نفس المصدر. في التوسّع الإنتاجي، انقل الجدولة إلى worker/queue مستقل.

## واجهات العرض

- `GET /api/customer/intelligence`: آخر 100 عنصر من المصادر المفعلة، للعميل النشط فقط.
- `GET /api/customer/assistant/status` و`POST /api/customer/assistant/chat`: حالة المساعد والمحادثة النصية للعميل النشط فقط.
- `/owner-console`: بوابة مالك مستقلة، لا يوجد رابط لها في واجهة العميل، وجميع البيانات والإجراءات محمية على الخادم.
- `GET /api/owner/integrations/sources`: قائمة المصادر، للمالك فقط.
- `POST /api/owner/integrations/sources`: إنشاء مصدر، للمالك فقط.
- `PATCH /api/owner/integrations/sources/{id}`: تفعيل/تعطيل مصدر، للمالك فقط.
- `POST /api/owner/integrations/sources/{id}/poll`: جلب RSS فورًا، للمالك فقط.

## الترحيل والاختبار

تضيف النسخة ترحيل Alembic رقم `0004_external_intelligence`. خذ نسخة احتياطية قبل التحديث، ثم نفّذ:

```bash
cd backend
alembic upgrade head
python -m pytest -q
```

تم بناء طبقة الاستقبال والعرض والتخزين والمساعد النصي القابل للربط بمزود خارجي. لا يوجد مزود AI أو مفتاح API مهيأ افتراضيًا؛ يجب أن يضبطه مالك الخادم. لا يملك المساعد صلاحية إصدار أوامر تداول.
