# Paste-ready demo cases

Paste one into "Try it" on the page and press "Run live".

## 1. Clean decline (expect: payment_declined, hidden_limit, auto-tag)

```
Cliente: Mi tarjeta fue rechazada en una compra de $18,500.00 MXN.
Agente: ¿Tu nombre y cuenta?
Cliente: Roberto Salinas, LP-224509, termina en 8043.
Agente: La tarjeta tiene un límite diario por transacción menor a ese monto, definido en la política de tu empresa.
Cliente: ¿Dónde veo ese límite? En la app no aparece.
Agente: No se muestra al titular, solo al admin. Pídele que lo suba o divide la compra.
```

## 2. Activation vs decline trap (expect: payment_declined, review queue for ambiguity)

```
Cliente: La activación falló, mi tarjeta no funciona. Termina en 2087.
Agente: ¿Tu nombre y cuenta?
Cliente: Eduardo Paredes, LP-551670.
Agente: La tarjeta está activa desde hace dos semanas. ¿Qué pasó al pagar?
Cliente: En una tienda me la rechazaron, $9,400.00 MXN.
Agente: Es un rechazo, no un fallo de activación. El monto superó tu límite por transacción.
Cliente: Ah, no sabía que tenía límite.
```

## 3. Risk case (expect: human-led, risk words)

```
Cliente: Me bloquearon la cuenta y vi un correo de ingreso desde otro país. No fui yo.
Agente: ¿Tu nombre y cuenta?
Cliente: Juan Esteban Mejía, LP-228731.
Agente: Veo un inicio de sesión desde una ubicación inusual. Bloqueamos por seguridad.
Cliente: Aprobaron un pago de $7.900.000 COP que no reconozco.
Agente: Escalo ahora a seguridad. Un especialista te llamará.
```

## For the live changes

- New risk word: add `contracargo` under `risk_words` in `config.yaml`, then paste:

```
Cliente: Hola, soy Marta Ríos, cuenta LP-551200. Quiero iniciar un contracargo por un cobro de $3,400.00 MXN que el comercio no me devolvió.
Agente: Entiendo, ¿qué terminación tiene la tarjeta?
Cliente: Termina en 7781.
```

- Threshold: set `auto_tag_min_confidence: 0.90`, then run `python3 run.py --only C039`: its 0.85 confidence moves from auto-tag to the review queue. Or paste case 1 on the page and watch the route line.
