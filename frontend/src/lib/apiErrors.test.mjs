import assert from "node:assert/strict";
import test from "node:test";
import { cleanPayload, parsearErrorApi } from "./apiErrors.ts";

test("parsearErrorApi: maneja detail como string", () => {
  const res = parsearErrorApi({ detail: "Stock insuficiente en almacén." }, 400);
  assert.equal(res.message, "Stock insuficiente en almacén.");
  assert.deepEqual(res.fieldErrors, {});
});

test("parsearErrorApi: traduce array 422 con múltiples campos", () => {
  const res = parsearErrorApi(
    {
      detail: [
        { loc: ["body", "almacen_destino_id"], msg: "Field required", type: "missing" },
        { loc: ["body", "correo"], msg: "value is not a valid email address", type: "value_error" },
      ],
    },
    422
  );
  assert.equal(res.fieldErrors.almacen_destino_id, "es obligatorio");
  assert.equal(res.fieldErrors.correo, "no es un correo electrónico válido");
  assert.match(res.message, /Almacén de destino: es obligatorio/);
  assert.match(res.message, /Correo electrónico: no es un correo electrónico válido/);
});

test("parsearErrorApi: formatea campos anidados en listas (detalles.0.costo_unitario_usd)", () => {
  const res = parsearErrorApi(
    {
      detail: [
        {
          loc: ["body", "detalles", 0, "costo_unitario_usd"],
          msg: "Input should be a valid decimal",
          type: "decimal_parsing",
        },
      ],
    },
    422
  );
  assert.equal(
    res.fieldErrors["detalles.0.costo_unitario_usd"],
    "debe ser un número válido"
  );
  assert.equal(
    res.message,
    "Detalles #1 → Costo unitario (USD): debe ser un número válido"
  );
});

test("cleanPayload: convierte strings vacíos opcionales a null y NaN a 0/null", () => {
  const limpio = cleanPayload({
    proveedor_nombre: "  Tech CA  ",
    serial: "",
    correo: "   ",
    costo_flete_usd: Number.NaN,
    precio_venta_usd: Number.NaN,
    items: [{ sku: "CO-01", serial: "" }],
  });
  assert.equal(limpio.proveedor_nombre, "Tech CA");
  assert.equal(limpio.serial, null);
  assert.equal(limpio.correo, null);
  assert.equal(limpio.costo_flete_usd, 0);
  assert.equal(limpio.precio_venta_usd, null);
  assert.equal(limpio.items[0].serial, null);
});
