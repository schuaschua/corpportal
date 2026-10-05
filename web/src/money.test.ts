import { describe, expect, it } from 'vitest';
import { formatAED, formatShortAED, formatSignedAED, parseAmountInput, toFils } from './money';

describe('money', () => {
  it('formats API strings as AED without float arithmetic', () => {
    expect(formatAED('1900000.00')).toBe('AED 1,900,000');
    expect(formatAED('-120000.00')).toBe('−AED 120,000');
    expect(formatAED('90071992547409931.07')).toBe('AED 90,071,992,547,409,931.07'); // > 2^53
    expect(formatSignedAED('590000.00')).toBe('+AED 590,000');
    expect(formatShortAED(toFils('1780000.00'))).toBe('AED 1.8m');
    expect(parseAmountInput('450,000')).toBe('450000.00');
    expect(parseAmountInput('0')).toBeNull();
    expect(parseAmountInput('1.234')).toBeNull();
  });
});
