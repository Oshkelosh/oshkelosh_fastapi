-- Shared supplier packing-slip / gift-message settings + order gift_message.
-- Fresh installs get the columns from SQLModel create_all.

ALTER TABLE site_settings ADD COLUMN packing_slip_message TEXT;
ALTER TABLE site_settings ADD COLUMN packing_slip_phone VARCHAR(64);
ALTER TABLE site_settings ADD COLUMN gift_messages_enabled BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE site_settings ADD COLUMN gift_message_max_length INTEGER NOT NULL DEFAULT 200;

ALTER TABLE orders ADD COLUMN gift_message TEXT;
