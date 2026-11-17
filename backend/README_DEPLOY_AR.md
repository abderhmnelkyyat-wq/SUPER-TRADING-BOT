# دليل نشر الخادم

## متطلبات النشر
- خادم Linux حديث (Ubuntu 22.04/24.04 مثلًا) مع Docker وDocker Compose.
- اسم نطاق DNS يشير إلى عنوان الخادم.
- السماح باتصالات TCP على 80 و443 حتى يحصل Caddy على شهادة TLS.
- إعداد `backend/.env` وملف `.env` الجذري بسرّية.

## إعداد أول مرة
```bash
cp .env.example .env
cp backend/.env.example backend/.env
./deploy/prepare_server.sh
```

بعد ذلك عدّل:
- `.env`: ضع نطاقك الحقيقي في `PUBLIC_DOMAIN`.
- `backend/.env`: ضع النطاق نفسه في `PUBLIC_APP_URL`، وراجع `CORS_ORIGINS`، ولا تضع مفاتيح حقيقية في Git. إعدادات `LIVE_TRADING_ENABLED` و`MT5_DEMO_ONLY` التي يقرأها Compose من `.env` الجذري يجب أن تطابق إعداد الخادم الداخلي، وتظل `false/true` على الترتيب حتى إتمام بوابات REAL.
- يمكن إضافة `TELEGRAM_BOT_TOKEN` و`ADMIN_TELEGRAM_CHAT_ID` لتلقي تنبيهات المالك.
- لتفعيل المساعد النصي، اضبط `AI_CHAT_API_URL` و`AI_CHAT_API_KEY` و`AI_CHAT_MODEL` داخل `backend/.env` فقط. يجب أن يكون الرابط HTTPS ومتوافقًا مع تنسيق Chat Completions. اتركها فارغة لتعطيل المساعد. لا تضع المفتاح في الواجهة أو Git. عند التشغيل اليدوي خارج Docker، حمّل `backend/.env` إلى بيئة العملية قبل تشغيل Uvicorn؛ ملف الإعداد لا يقرأ أسرار `.env` تلقائيًا.

تأكد من أن قيمة `POSTGRES_PASSWORD` في `.env` لا تُشارك. ينشئ السكربت سرّي `AUTH_SECRET` وسرّي `LICENSE_PEPPER` منفصلين.

## التشغيل
```bash
docker compose up -d --build
docker compose ps
docker compose logs -f app
```

لا تنشئ حساب المالك قبل نجاح ترحيل قاعدة البيانات وظهور حالة `/api/health` بحالة `ok`.

## إنشاء حساب المالك
```bash
docker compose exec app python backend/scripts/create_owner.py --email owner@your-domain.example --name "Application Owner"
```
أدخل كلمة مرور قوية عند الطلب. لا توجد كلمة مرور افتراضية أو حساب Admin مضمّن.

## تثبيت التطبيق
بوابة المالك المستقلة: افتح المسار `/owner-console` مباشرة من عنوان الخادم. لا يظهر رابطها في واجهة العميل، كما أن كل بيانات الإدارة وعملياتها محمية بتفويض Owner على الخادم.

افتح النطاق باستخدام HTTPS:
- Android: Chrome ← القائمة ← Install app أو Add to Home screen.
- iPhone/iPad: Safari ← Share ← Add to Home Screen.
- Windows/macOS: Edge أو Chrome ← Install app.

التطبيق PWA متعدد المنصات. لا يحتاج المستخدم إلى متجر تطبيقات لتثبيته. يتطلب إصدار APK/EXE موقّع للنشر في المتاجر طبقة تغليف Native مستقلة وشهادات توقيع يملكها الناشر.

## تحديث النسخة
```bash
git pull
docker compose up -d --build
```
تُطبّق Alembic migrations عند تشغيل الحاوية. أنشئ نسخة احتياطية قبل كل تحديث:
```bash
./deploy/backup_postgres.sh
```

## إعداد تنبيهات Telegram
أنشئ Bot من BotFather، ثم ضع `TELEGRAM_BOT_TOKEN` و`ADMIN_TELEGRAM_CHAT_ID` في `backend/.env` وأعد تشغيل الخدمة:
```bash
docker compose up -d --force-recreate app
```
يُرسل الخادم تنبيه طلب اشتراك، واعتماد الاشتراك، والصفقات الرابحة والعمولات المستحقة. لا يرسل رمز الترخيص عبر Telegram؛ يظهر للمالك مرة واحدة عند الاعتماد داخل لوحة الإدارة.

## إعداد Windows MT5 Agent
راجع `mt5-agent/README_AR.md` وقائمة `docs/LIVE_TRADING_GO_LIVE_CHECKLIST_AR.md`. لا يعمل موصل MT5 الرسمي على Android/Termux؛ يجب تشغيله على Windows مع MT5 Terminal مسجل الدخول. لا تدخل كلمة مرور MT5 في تطبيق الويب أو ترسلها إلى الخادم.

## التداول الحقيقي — مدمج ومغلق افتراضيًا
إصدار 1.2.0 يتضمن مسار تنفيذ REAL داخل Windows MT5 Agent مع بوابات موافقة مستقلة. الافتراضي:
```env
LIVE_TRADING_ENABLED=false
MT5_DEMO_ONLY=true
```
ولا تُغيّرها الآن. فتحه يتطلب اكتمال كل التالي: مراجعة قانونية وتنظيمية، مراجعة أمان، اختبار DEMO موثق لدى نفس الوسيط، إتمام إعداد خادم الإنتاج، موافقة العميل العامة وموافقته المستقلة على مخاطر REAL في الواجهة، ثم إعداد `ENABLE_LIVE_EXECUTION=true` وعبارة التأكيد المحلية داخل `.env` الخاص بالوكيل. يجب أن تكون هذه القيم متوافقة على الخادم والوكيل. أي بوابة مفقودة تمنع `order_send`.

لا تفعّل REAL في نسخة الاختبار ولا تستخدم حسابًا لا تملك صلاحية إدارته. احتفظ بحساب مخصص للوكيل. حدود البدء المحافظة: 0.25% مخاطرة مبدئية لكل صفقة، 1% خسارة يومية، 1% إجمالي مخاطرة مفتوحة، 3 مراكز إجمالًا ومركز واحد لكل رمز. هذه حدود تشغيلية وليست ضمانًا ضد فجوات الأسعار أو الانزلاق أو خسائر تتجاوز وقف الخسارة.
