# Stock Liquidity GitHub starter — Finnhub

هذه نسخة بداية تستخدم Finnhub لجلب الأسعار وتستخدم مقياس متوسط حجم التداول إن كان متاحًا في خطتك. **ليست بيانات حجم تداول لحظي لكل السوق**: نقطة `/quote` لا تعيد حجم التداول الحالي، ولذلك يحسب `dollar_volume` هنا كقيمة تقريبية لمتوسط السيولة (السعر الحالي × متوسط حجم التداول لـ10 أيام، مع الرجوع إلى 3 أشهر إن لزم). إذا رفضت خطتك endpoint `/stock/metric`، سيترك البرنامج قيمة السيولة فارغة بدل اختلاقها.

## قيود مهمة
- حد الخطة المجانية يُذكر عادةً بنحو 60 طلب API في الدقيقة، لكن تحقق من حسابك وصفحة Finnhub الحالية؛ بعض النهايات قد تكون مدفوعة.
- كل تشغيل يجلب 25 سهمًا بحد أقصى (طلب quote + طلب metric لكل سهم). الجدولة كل 5 دقائق، لذا يتحدّث جزء من القائمة في كل مرة وتظل بقية الأسهم مخزنة ببيانات أقدم. لا يمكن تحديث جميع الأسهم الأمريكية كل دقيقة باستخدام GitHub Actions وواجهة REST المجانية.
- قائمة الرموز تُجمع من أدلة Nasdaq Trader العامة (Nasdaq + other-listed) وليست ضمانًا بأن Finnhub يدعم كل رمز.
- تحديث GitHub Actions المجدول ليس مضمونًا في الدقيقة المحددة؛ الحد الأدنى المعتاد للجدولة 5 دقائق.

## الإعداد
1. ارفع محتويات المجلد إلى مستودع GitHub.
2. من `Settings → Secrets and variables → Actions` أضف Secret باسم `FINNHUB_API_KEY` وقيمته مفتاح Finnhub. لا تضع المفتاح في HTML أو في أي ملف بالمستودع.
3. فعّل Actions ثم شغّل `Update US stock liquidity data` يدويًا.
4. بعد نجاح التشغيل، انشر المستودع عبر GitHub Pages أو استخدم رابط Raw العام لـ `data/latest.json`.
5. الصق رابط JSON في خانة رابط البيانات في ملف HTML.

## الحساب
`dollar_volume = current_quote_price × average_volume_10d`. هذا **متوسط سيولة تقديري** وليس إجمالي قيمة التداول الحالية اليوم. لا يستخدم للتداول الآلي أو قرارات مالية دون التحقق من مصدر مرخّص وملائم.

## الروابط
- Finnhub API docs: https://finnhub.io/docs/api
- Finnhub pricing: https://finnhub.io/pricing
- Nasdaq Trader symbol directories: https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs
