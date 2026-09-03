/**
 * ContractIQ - Dredd Hooks
 *
 * Dredd's transactions use the static `example` IDs from the OpenAPI spec
 * ("sample-pet-id-001", "sample-order-id-001"), which don't exist in the
 * live API's in-memory database — so every GET/PUT/DELETE-by-ID
 * transaction fails with a 404 that has nothing to do with a real
 * contract problem.
 *
 * These hooks intercept transactions before they run and substitute a
 * REAL pet/order ID (created via a live API call) in place of the fake
 * example ID, so Dredd is actually testing contract conformance against
 * real data instead of testing "does this fake ID 404" over and over.
 */
const hooks = require('hooks');
const http = require('http');

let realPetId = null;
let realOrderId = null;
let deletePetId = null;

function httpRequest(options, body) {
  return new Promise((resolve, reject) => {
    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          resolve({ statusCode: res.statusCode, body: JSON.parse(data || '{}') });
        } catch (e) {
          resolve({ statusCode: res.statusCode, body: {} });
        }
      });
    });
    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

hooks.beforeAll(async (transactions, done) => {
  try {
    const petPayload = {
      name: 'Dredd Test Pet', species: 'Dog', age: 2,
      status: 'available', tags: ['dredd'], price: 100.0,
    };
    const createPet = await httpRequest({
      hostname: 'localhost', port: 8000, path: '/api/v1/pets',
      method: 'POST', headers: { 'Content-Type': 'application/json' },
    }, petPayload);
    if (createPet.statusCode === 201) {
      realPetId = createPet.body.id;
    }

    const createDeletePet = await httpRequest({
      hostname: 'localhost', port: 8000, path: '/api/v1/pets',
      method: 'POST', headers: { 'Content-Type': 'application/json' },
    }, { ...petPayload, name: 'Dredd Disposable Pet' });
    if (createDeletePet.statusCode === 201) {
      deletePetId = createDeletePet.body.id;
    }

    if (realPetId) {
      const createOrder = await httpRequest({
        hostname: 'localhost', port: 8000, path: '/api/v1/orders',
        method: 'POST', headers: { 'Content-Type': 'application/json' },
      }, { pet_id: realPetId, quantity: 1 });
      if (createOrder.statusCode === 201) {
        realOrderId = createOrder.body.id;
      }
    }

    console.log(`[Dredd Hooks] Seeded real IDs — pet: ${realPetId}, delete-pet: ${deletePetId}, order: ${realOrderId}`);
  } catch (e) {
    console.log('[Dredd Hooks] Could not seed live IDs, falling back to spec examples:', e.message);
  }
  done();
});

hooks.beforeEach((transaction, done) => {
  const isDelete = transaction.request.method === 'DELETE';
  const isCreateOrder = transaction.request.method === 'POST'
    && transaction.fullPath.replace(/\?.*$/, '') === '/api/v1/orders';
  const petIdToUse = isDelete ? deletePetId : realPetId;

  const expectedStatus = transaction.expected && transaction.expected.statusCode;
  const expectsNotFound = expectedStatus === '404' || expectedStatus === 404;
  const expectsValidationError = expectedStatus === '422' || expectedStatus === 422;

  const isCreatePet = transaction.request.method === 'POST'
    && transaction.fullPath.replace(/\?.*$/, '') === '/api/v1/pets';

  // create_pet's 422 case: the spec's example body is now deliberately
  // valid (so the 201 success case passes), which means the transaction
  // testing "invalid input -> 422" needs its own corrupted body instead.
  if (isCreatePet && expectsValidationError) {
    try {
      const body = JSON.parse(transaction.request.body || '{}');
      body.price = -10; // violates exclusiveMinimum: 0 -> 422
      body.age = 999;   // violates maximum: 30 -> 422
      transaction.request.body = JSON.stringify(body);
    } catch (e) { /* leave body as-is if it isn't valid JSON */ }
    done();
    return;
  }

  // create_order's 422 case needs a REAL pet_id (so it clears the
  // "pet exists" check) but an invalid quantity (so it fails schema
  // validation instead) — a fake pet_id there would always 404 first,
  // never reaching the validation Dredd is actually trying to test.
  if (isCreateOrder && expectsValidationError && realPetId) {
    try {
      const body = JSON.parse(transaction.request.body || '{}');
      body.pet_id = realPetId;
      body.quantity = 999; // exceeds the schema's maximum of 10 -> 422
      transaction.request.body = JSON.stringify(body);
    } catch (e) { /* leave body as-is if it isn't valid JSON */ }
    done();
    return;
  }

  // create_order's SUCCESS case: pet_id lives in the request BODY, not
  // the URL, so the generic path-based substitution below never reaches
  // it — patch the body directly here instead.
  if (isCreateOrder && !expectsNotFound && !expectsValidationError && realPetId) {
    try {
      const body = JSON.parse(transaction.request.body || '{}');
      body.pet_id = realPetId;
      transaction.request.body = JSON.stringify(body);
    } catch (e) { /* leave body as-is if it isn't valid JSON */ }
    done();
    return;
  }

  if (!expectsNotFound) {
    if (petIdToUse) {
      transaction.fullPath = transaction.fullPath.replace('sample-pet-id-001', petIdToUse);
      transaction.request.uri = transaction.request.uri.replace('sample-pet-id-001', petIdToUse);
    }
    if (realOrderId) {
      transaction.fullPath = transaction.fullPath.replace('sample-order-id-001', realOrderId);
      transaction.request.uri = transaction.request.uri.replace('sample-order-id-001', realOrderId);
    }
  }
  done();
});
