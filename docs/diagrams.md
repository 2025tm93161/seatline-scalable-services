# Editable diagrams

## Components

```mermaid
flowchart TB
    Client[JavaScript console / HTTP scripts] -->|REST HTTP JSON| Booking[Booking: saga owner]
    Booking -->|REST HTTP: reserve / release| Inventory[Inventory: capacity owner]
    Booking -->|REST HTTP: charge / refund| Payment[Payment: mock gateway]
    Booking -->|REST HTTP: deliver| Notification[Notification: mock provider]
    Booking -->|SQL: booking_user| B[(booking DB)]
    Inventory -->|SQL: inventory_user| I[(inventory DB)]
    Payment -->|SQL: payment_user| P[(payment DB)]
    Notification -->|SQL: notification_user| N[(notification DB)]
```

## Main transaction and step-three failure

```mermaid
sequenceDiagram
    participant C as Client
    participant B as Booking
    participant I as Inventory
    participant P as Payment mock
    participant N as Notification mock
    C->>B: POST /api/v1/bookings + Idempotency-Key + X-Request-ID
    B->>B: Lock key and persist PENDING and payload
    B->>I: POST /api/v1/holds (deterministic booking ID)
    I->>I: Atomic conditional UPDATE + insert hold + save replay
    I-->>B: 201 amount_cents
    B->>B: Persist RESERVED
    B->>P: POST /api/v1/charges + stable key
    P-->>B: 201 CHARGED
    B->>B: Persist PAID
    B->>N: POST /api/v1/deliveries + stable key
    alt notification succeeds
        N-->>B: 201 DELIVERED
        B->>B: Persist CONFIRMED + original response
        B-->>C: 201 CONFIRMED
    else forced step-three failure
        N-->>B: 503 PROVIDER_UNAVAILABLE
        B->>B: Persist COMPENSATING
        B->>P: POST /charges/{id}/refund
        P-->>B: 200 REFUNDED
        B->>I: POST /holds/{id}/release
        I-->>B: 200 RELEASED
        B->>B: Persist CANCELLED + original response
        B-->>C: 409 CANCELLED business outcome
    end
```

Each inter-service arrow is HTTP JSON. Each service commits only its own database.
If a compensation call fails, persist COMPENSATION_PENDING; after restoring the service,
the operator invokes recover. Stable IDs and local fences make repeated work harmless.

## Booking state machine

```mermaid
stateDiagram-v2
    [*] --> PENDING
    PENDING --> RESERVED: inventory accepted
    RESERVED --> PAID: payment charged
    PAID --> CONFIRMED: notification delivered
    PENDING --> COMPENSATING: dependency failure
    RESERVED --> COMPENSATING: decline or timeout
    PAID --> COMPENSATING: notification failure
    COMPENSATING --> CANCELLED: refund and release acknowledged
    COMPENSATING --> COMPENSATION_PENDING: compensation failed
    COMPENSATION_PENDING --> COMPENSATING: explicit recovery
    CONFIRMED --> [*]
    CANCELLED --> [*]
```

## Inventory ER

```mermaid
erDiagram
    events ||--o{ holds : contains
    events { text id PK text name int capacity int available int price_cents }
    holds { text id PK text event_id FK int quantity text state }
    released_holds { text id PK }
    idempotency { text key PK text fingerprint int status text response }
```

## Booking ER

```mermaid
erDiagram
    bookings ||--o{ transitions : records
    bookings { text id PK text payload text state int amount_cents text reason }
    transitions { bigint sequence PK text booking_id FK text state timestamp created_at }
    idempotency { text key PK text fingerprint int status text response }
```

## Payment ER

```mermaid
erDiagram
    payments { text booking_id PK int amount_cents text state }
    idempotency { text key PK text fingerprint int status text response }
```

## Notification ER

```mermaid
erDiagram
    deliveries { text booking_id PK text recipient text state }
    idempotency { text key PK text fingerprint int status text response }
```

`booking_id` in Payment/Notification and a hold's ID reference a remote concept, **not a
cross-database foreign key**. Only events-to-holds and bookings-to-transitions are local FKs.