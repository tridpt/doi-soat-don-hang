import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const projectDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dataDir = path.join(projectDir, "data");
const orderPath = path.join(dataDir, "demo_orders_2026_09.xlsx");
const paymentPath = path.join(dataDir, "demo_payments_2026_09.xlsx");

const channels = ["Website", "Shopee", "TikTok Shop", "Facebook"];
const methods = ["Chuyển khoản", "Ví điện tử", "COD", "Thẻ"];
const orderId = (number) => `DH2609${String(number).padStart(3, "0")}`;
const orderDay = (number) => Math.floor(((number - 1) * 28) / 60) + 1;
const date = (day, month = 9) => new Date(Date.UTC(2026, month - 1, day));

const orders = [];
const payments = [];
let nextTransaction = 1;

function addPayment(number, amount, status = "Thành công", dayOffset = 0, methodIndex = number) {
  const day = orderDay(number);
  const row = [
    `GD2609${String(nextTransaction++).padStart(4, "0")}`,
    orderId(number),
    date(day + dayOffset),
    amount,
    status,
    methods[methodIndex % methods.length],
  ];
  payments.push(row);
  return row;
}

for (let number = 1; number <= 60; number++) {
  const merchandise = (180 + ((number * 13) % 37) * 23) * 1000;
  const shipping = number % 5 === 0 ? 0 : number % 2 === 0 ? 20_000 : 30_000;
  const discount = number % 7 === 0 ? 70_000 : number % 3 === 0 ? 30_000 : 0;
  const total = merchandise + shipping - discount;
  const status = [50, 51, 56, 57].includes(number)
    ? "Đã hủy"
    : number % 6 === 0 ? "Đang xử lý" : "Hoàn thành";
  orders.push([
    orderId(number),
    date(orderDay(number)),
    `KH${String(number).padStart(4, "0")}`,
    channels[(number - 1) % channels.length],
    merchandise,
    shipping,
    discount,
    total,
    status,
  ]);

  if (number <= 45 || number === 58 || number === 60) {
    addPayment(number, total);
  } else if (number === 46 || number === 59) {
    const firstPart = Math.floor(total / 2 / 1000) * 1000;
    addPayment(number, firstPart);
    addPayment(number, total - firstPart, "Thành công", 1);
    if (number === 59) addPayment(number, total, "Đang chờ", 2);
  } else if (number === 47 || number === 57) {
    // No payment was exported for these orders.
  } else if (number === 48) {
    addPayment(number, total - 90_000);
  } else if (number === 49) {
    addPayment(number, total + 60_000);
  } else if (number === 50) {
    addPayment(number, total);
    addPayment(number, total, "Đã hoàn tiền", 3);
  } else if (number === 51) {
    addPayment(number, total);
  } else if (number === 52) {
    addPayment(number, total, "Đang chờ");
  } else if (number === 53) {
    addPayment(number, total, "Thất bại");
  } else if (number === 54) {
    const transaction = addPayment(number, total);
    payments.push([...transaction]);
  } else if (number === 55) {
    addPayment(number, total);
    addPayment(number, 80_000, "Đã hoàn tiền", 3);
  } else if (number === 56) {
    addPayment(number, total);
    addPayment(number, 100_000, "Đã hoàn tiền", 3);
  }
}

payments.push([
  `GD2609${String(nextTransaction++).padStart(4, "0")}`,
  "DH269999",
  date(24),
  235_000,
  "Thành công",
  "Ví điện tử",
]);

if (orders.length !== 60 || payments.length !== 66) {
  throw new Error(`Unexpected row counts: ${orders.length} orders, ${payments.length} payments`);
}

async function createWorkbook(sheetName, headers, rows, widths, dateColumn, moneyColumns, outputPath) {
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add(sheetName);
  const lastColumn = String.fromCharCode(64 + headers.length);
  const lastRow = rows.length + 1;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.getRange(`A1:${lastColumn}${lastRow}`).values = [headers, ...rows];
  sheet.getRange(`A1:${lastColumn}${lastRow}`).format.font = { name: "Arial", size: 10, color: "#243047" };
  sheet.getRange(`A1:${lastColumn}1`).format = {
    fill: "#17365D",
    font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
    rowHeight: 27,
    verticalAlignment: "center",
  };
  sheet.getRange(`${dateColumn}2:${dateColumn}${lastRow}`).setNumberFormat("dd/mm/yyyy");
  for (const column of moneyColumns) {
    sheet.getRange(`${column}2:${column}${lastRow}`).setNumberFormat("#,##0");
  }
  for (let index = 0; index < widths.length; index++) {
    const column = String.fromCharCode(65 + index);
    sheet.getRange(`${column}1:${column}${lastRow}`).format.columnWidth = widths[index];
  }
  workbook.recalculate();
  const inspected = await workbook.inspect({
    kind: "region",
    sheetId: sheetName,
    range: `A1:${lastColumn}5`,
    maxChars: 2800,
    tableMaxRows: 5,
    tableMaxCols: headers.length,
  });
  console.log(`${sheetName}: ${rows.length} rows`);
  console.log(inspected.ndjson ?? inspected);
  const file = await SpreadsheetFile.exportXlsx(workbook);
  await file.save(outputPath);
}

await fs.mkdir(dataDir, { recursive: true });
await createWorkbook(
  "Don_hang",
  ["Mã đơn", "Ngày đặt", "Khách hàng", "Kênh bán", "Tiền hàng", "Phí giao hàng", "Giảm giá", "Tổng tiền", "Trạng thái"],
  orders,
  [17, 15, 15, 18, 17, 18, 16, 17, 17],
  "B",
  ["E", "F", "G", "H"],
  orderPath,
);
await createWorkbook(
  "Giao_dich",
  ["Mã giao dịch", "Mã đơn", "Ngày giao dịch", "Số tiền", "Trạng thái thanh toán", "Phương thức"],
  payments,
  [20, 17, 18, 18, 24, 18],
  "C",
  ["D"],
  paymentPath,
);
for (const outputPath of [orderPath, paymentPath]) {
  if ((await fs.stat(outputPath)).size < 1000) throw new Error(`Incomplete workbook: ${outputPath}`);
  await fs.rm(`${outputPath}.inspect.ndjson`, { force: true });
}
console.log(`Saved ${orderPath} and ${paymentPath}`);
