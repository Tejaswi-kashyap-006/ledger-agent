# Test data from the web

Everything else in `sample_data/` is made by `ledger demo` and the scripts in `scripts/`, so it fits the
readers by construction. The files here come from other people, so they test the parts that would meet
real documents. None of the files here is a real person's bank statement.

## Statements (`statements/`)

Two digital PDF statements, each with the dataset's own answers (`.json`), from the
[AgamiAI Indian Bank Statement Synthetic Dataset](https://huggingface.co/datasets/AgamiAI/Indian-Bank-Statements)
(synthetic business current accounts, Apache-2.0, © AgamiAI Inc.). Each page carries a diagonal
"SYNTHETIC DATA - MACHINE GENERATED" watermark.

| File | Layout | What it tests |
|---|---|---|
| `agami_type1_00001.pdf` | Txn Date (with a time) / Value Date / Cheque No. / Description / Branch / Debit / Credit / Balance, amounts as `Rs. 6,086.63` | the watermark, dates with times, wrapped narrations under a centred header, column positions that shift from page to page |
| `agami_type2_00003.pdf` | No. / ID / Value Date / Txn Posted Date / Cheque No. / Description / Cr/Dr / Amount / Balance | a Dr/Cr column, a "Page 5" footer on the same line as a row, a short amount that sits nearer the balance column |

Result (`tests/test_web_samples.py`; the same check over 46 statements of both layouts): every row is
found, and every transaction's date, amount and balance match the answers to the paisa (7,379 of 7,379).
Rows marked `FAILED-INSUFFICIENT FUNDS` show no amount and are skipped. About 4% of narrations differ
by one space, where the generator broke a word across two lines ("ABHIJI / T DAS").

**These statements don't import, and they shouldn't.** The dataset's own balances don't add up: on 6 to 18%
of rows, the balance moves by a different amount than the transaction (check the `.json` files). The
balance sensor reports exactly that and refuses the file, which is the job it's there for.

## Bills (`bills/`)

Resized to 864 to 1100 px wide and saved without EXIF data. Each keeps the licence of its original;
for the CC BY-SA files, the resized copy is under the same licence.

| File | Source | Licence | What a correct reading says |
|---|---|---|---|
| `gaurav_mess_bill_kota.jpg` | [Foodmessbillmarch.jpg](https://commons.wikimedia.org/wiki/File:Foodmessbillmarch.jpg), Virath guru, Wikimedia Commons | CC0 | handwritten: ₹3,800 on 16 Feb 2024, one line for the month's mess fees (Food) |
| `kollam_prepaid_auto.jpg` | [Kollam prepaid autorickshaw receipt, Dec 2018](https://commons.wikimedia.org/wiki/File:Kollam_prepaid_autorickshaw_receipt,_Dec_2018.jpg), Arunvrparavur, Wikimedia Commons | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | ₹27 on 15 Dec 2018 (not ₹2, the coupon printed above it), Cab & Auto |
| `blank_cash_bill_mysore.jpg` | [Bill in a local restaurant, Mysore, Karnataka](https://commons.wikimedia.org/wiki/File:Bill_in_a_local_restaurant,_Mysore,_Karnataka.jpg), Subhashish Panigrahi, Wikimedia Commons | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) | an empty bill form: refused, nothing is stored |
| `cord_receipt_test4.jpg` | [CORD v2](https://huggingface.co/datasets/naver-clova-ix/cord-v2), test split, row 4, NAVER Clova | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | a crumpled Indonesian receipt: three items less a 19,400 discount = 174,600 (rupiah, so no rupee payment matches it) |

Read live with `gpt-5.4-mini` (2026-11-21): all four came out right, after two instruction fixes they
showed up. A bill that has only a total now comes back as one line, so it isn't flagged "doesn't add
up", and a discount now takes its items' category. The model can't tell rupiah from rupees, and with the
shop name blurred it named the shop after an item. Neither does harm, because a bill only pins to a
payment of exactly its amount.
