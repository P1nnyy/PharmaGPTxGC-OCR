/**
 * Rule 46(b) invoice serials, allocated to a device in blocks.
 *
 * Two constraints shape this, and they pull against each other:
 *
 *  * The house rule forbids generating a serial from a server call at sale
 *    time. A counter that cannot bill because the network is down is not an
 *    acceptable failure mode, and a serial handed out per sale would also
 *    leave gaps in the series whenever a request failed halfway.
 *  * A serial feeds a filed return, so it cannot live in a browser store.
 *
 * The resolution is to move the server call *earlier*: a device asks for a
 * block of serials ahead of time, and consumes them locally as bills are
 * issued. The block is requested when the counter opens, not when a customer
 * is standing there.
 *
 * WHERE THE UNCONSUMED CURSOR LIVES IS STILL AN OPEN DECISION - see
 * `SerialBlockStore`. It is expressed as an injected interface precisely so
 * that the answer is one adapter rather than a change threaded through the
 * screen.
 */

/** A block of consecutive serials issued to one device. */
export interface SerialBlock {
  /** Series prefix, e.g. the device's counter code. Part of the serial. */
  prefix: string;
  /** Financial year the block belongs to, `YYYY-YY`. Serials are unique
   *  within a financial year, so a block never spans one. */
  financial_year: string;
  /** First and last sequence number in the block, inclusive. */
  from_sequence: number;
  to_sequence: number;
  /** Next sequence to hand out. Equal to `to_sequence + 1` when exhausted. */
  next_sequence: number;
  /** Zero-padding width, so the series sorts lexicographically. */
  pad_to: number;
}

/**
 * Where a partially-consumed block is kept between bills.
 *
 * Deliberately NOT implemented over localStorage: a serial feeds a return, and
 * the house rules put returns-bound data in Neo4j and nowhere else. The
 * remaining candidates - a server-side per-device cursor, or the offline
 * outbox that the rules do carve out - are a decision the product owner has to
 * make, so this stays an interface until then.
 */
export interface SerialBlockStore {
  read(): Promise<SerialBlock | null>;
  /** Persists the advanced cursor. Must complete before the bill is shown as
   *  issued, or a crash could reuse a serial. */
  write(block: SerialBlock): Promise<void>;
}

/**
 * A store that survives nothing.
 *
 * The default only because the alternatives are all wrong: a localStorage
 * implementation would violate the house rules quietly, whereas this one fails
 * loudly and visibly on reload, which is the correct behaviour while the real
 * answer is outstanding.
 */
export function createEphemeralStore(): SerialBlockStore {
  let held: SerialBlock | null = null;
  return {
    read: async () => held,
    write: async (block) => {
      held = block;
    }
  };
}

/** Rule 46(b): alphanumerics plus `-` and `/`, at most 16 characters. */
const RULE_46B = /^[A-Za-z0-9/-]{1,16}$/;

export function isValidSerial(serial: string): boolean {
  return RULE_46B.test(serial);
}

/** The financial year (`2026-27`) an ISO date falls in. April to March. */
export function financialYearOf(isoDate: string): string {
  const [year, month] = isoDate.split('-').map(Number);
  const startYear = month >= 4 ? year : year - 1;
  return `${startYear}-${String((startYear + 1) % 100).padStart(2, '0')}`;
}

export function formatSerial(block: SerialBlock, sequence: number): string {
  return `${block.prefix}${String(sequence).padStart(block.pad_to, '0')}`;
}

export class SerialUnavailableError extends Error {}

/**
 * Takes the next serial from the device's block and advances the cursor.
 *
 * The cursor is persisted *before* the serial is returned. Handing out a
 * number and then failing to record that it was used is the one ordering that
 * can duplicate a serial across two bills, so it is not the ordering used.
 */
export async function consumeSerial(
  store: SerialBlockStore,
  onDate: string
): Promise<string> {
  const block = await store.read();
  if (block === null) {
    throw new SerialUnavailableError(
      'This counter has no serial block. Request one before billing.'
    );
  }
  if (block.next_sequence > block.to_sequence) {
    throw new SerialUnavailableError(
      'This counter has used its whole serial block. Request another before billing.'
    );
  }
  const expectedFy = financialYearOf(onDate);
  if (block.financial_year !== expectedFy) {
    throw new SerialUnavailableError(
      `This block belongs to ${block.financial_year}, but the bill date falls in ${expectedFy}. Request a block for the current year.`
    );
  }

  const sequence = block.next_sequence;
  const serial = formatSerial(block, sequence);
  if (!isValidSerial(serial)) {
    throw new SerialUnavailableError(
      `"${serial}" is not a valid Rule 46(b) serial. Check the series prefix.`
    );
  }

  await store.write({ ...block, next_sequence: sequence + 1 });
  return serial;
}

/** Serials left in the block, for the counter to see before it runs out. */
export const remainingInBlock = (block: SerialBlock | null): number =>
  block === null ? 0 : Math.max(0, block.to_sequence - block.next_sequence + 1);
