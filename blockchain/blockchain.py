from collections import OrderedDict

import binascii
import copy

import Crypto
import Crypto.Random
from Crypto.Hash import SHA
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5

import hashlib
import json
from time import time
from urllib.parse import urlparse
from uuid import uuid4

import requests
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

MINING_SENDER = "THE BLOCKCHAIN"
MINING_REWARD = 1
MINING_DIFFICULTY = 2
filename = 'chainData/chain.json'

class Blockchain:

    def __init__(self):
        filedata = self.load_chain_from_file()
        self.transactions = []
        self.chain = filedata['chain'] if filedata else []
        self.nodes = set(filedata['nodes']) if filedata else set()
        self.node_id = filedata['node_id'] if filedata else str(uuid4()).replace('-', '')
        if not filedata:
            self.create_block(0, '00')

    def load_chain_from_file(self):
        with open(filename, 'r') as f:
            # if f.read() == "":
            #     return False
            data = json.load(f)
            return data

    def save_chain_in_file(self):
        with open(filename, 'w') as f:
            data = {
                'node_id': self.node_id,
                'nodes': list(self.nodes),
                'chain': self.chain
            }
            f.write(json.dumps(data, indent=4))

    def register_node(self, node_url):
        parsed_url = urlparse(node_url)
        if parsed_url.netloc:
            self.nodes.add(parsed_url.netloc)
        elif parsed_url.path:
            self.nodes.add(parsed_url.path)
        else:
            raise ValueError('Invalid URL')

    def verify_transaction_signature(self, sender_address, signature, transaction):
        public_key = RSA.importKey(binascii.unhexlify(sender_address))
        verifier = PKCS1_v1_5.new(public_key)
        h = SHA.new(str(transaction).encode('utf8'))
        return verifier.verify(h, binascii.unhexlify(signature))

    def submit_transaction(self, sender_address, recipient_address, value, signature):
        transaction = OrderedDict({'sender_address': sender_address, 
                                    'recipient_address': recipient_address,
                                    'value': value})

        if sender_address == MINING_SENDER:

            self.transactions.append(transaction)
            return len(self.chain) + 1
        else:
            transaction_verification = self.verify_transaction_signature(sender_address, signature, transaction)
            print(transaction_verification)
            if transaction_verification:
                transaction = OrderedDict({'sender_address': sender_address,
                                    'recipient_address': recipient_address,
                                    'value': value,
                                    'signature': signature})
                self.transactions.append(transaction)
                return len(self.chain) + 1
            else:
                return False

    def create_block(self, nonce, previous_hash):
        block = {'block_number': len(self.chain) + 1,
                 'timestamp': time(),
                 'transactions': self.transactions,
                 'nonce': nonce,
                 'previous_hash': previous_hash}
        self.transactions = []
        self.chain.append(block)

        self.save_chain_in_file()
        return block

    def hash(self, block):
        block_string = json.dumps(block, sort_keys=True).encode()

        return hashlib.sha256(block_string).hexdigest()

    def proof_of_work(self):
        last_block = self.chain[-1]
        last_hash = self.hash(last_block)

        nonce = 0
        while self.valid_proof(self.transactions, last_hash, nonce) is False:
            nonce += 1

        return nonce

    def valid_proof(self, transactions, last_hash, nonce, difficulty=MINING_DIFFICULTY):
        guess = (str(transactions) + str(last_hash) + str(nonce)).encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:difficulty] == '0' * difficulty

    def valid_chain(self, chain):
        last_block = chain[0]
        current_index = 1

        while current_index < len(chain):
            block = chain[current_index]
            if block['previous_hash'] != self.hash(last_block):
                return False
            transactions = block['transactions'][:-1]
            transaction_elements = ['sender_address', 'recipient_address', 'value', 'signature']
            transactions = [OrderedDict((k, transaction[k]) for k in transaction_elements) for transaction in
                            transactions]

            if not self.valid_proof(transactions, block['previous_hash'], block['nonce'], MINING_DIFFICULTY):
                return False

            last_block = block
            current_index += 1

        return True

    def resolve_conflicts(self):
        neighbours = self.nodes
        new_chain = None

        max_length = len(self.chain)

        for node in neighbours:
            print('http://' + node + '/chain')
            response = requests.get('http://' + node + '/chain')

            if response.status_code == 200:
                length = response.json()['length']
                chain = response.json()['chain']

                if length > max_length and self.valid_chain(chain):
                    max_length = length
                    new_chain = chain

        if new_chain:
            self.chain = new_chain
            return True

        return False


app = Flask(__name__)
CORS(app)

blockchain = Blockchain()


@app.route('/')
def index():
    return render_template('./index.html')


@app.route('/configure')
def configure():
    return render_template('./configure.html')


@app.route('/transactions/new', methods=['POST'])
def new_transaction():
    values = request.form

    required = ['sender_address', 'recipient_address', 'amount', 'signature']
    if not all(k in values for k in required):
        return 'Missing values', 400
    transaction_result = blockchain.submit_transaction(values['sender_address'], values['recipient_address'],
                                                       values['amount'], values['signature'])

    if transaction_result == False:
        response = {'message': 'Invalid Transaction!'}
        return jsonify(response), 406
    else:
        response = {'message': 'Transaction will be added to Block ' + str(transaction_result)}
        return jsonify(response), 201


@app.route('/transactions/get', methods=['GET'])
def get_transactions():
    transactions = blockchain.transactions

    response = {'transactions': transactions}
    return jsonify(response), 200


@app.route('/chain', methods=['GET'])
def full_chain():
    values = request.args
    chains = copy.deepcopy(blockchain.chain)
    arrayss = []
    if values.get('transactions_my') and values['transactions_my'] != 'false':
        for chain in chains:
            transactions = chain['transactions']
            for transaction in transactions:
                if transaction['recipient_address'] == values['open_key'] or transaction['sender_address'] == values['open_key']:
                    arrayss.append(transaction)
            chain['transactions'] = arrayss
            arrayss = []
    response = {
        'chain': chains,
        'length': len(blockchain.chain),
    }
    return jsonify(response), 200


@app.route('/mine', methods=['GET'])
def mine():
    last_block = blockchain.chain[-1]
    nonce = blockchain.proof_of_work()

    blockchain.submit_transaction(sender_address=MINING_SENDER, recipient_address=blockchain.node_id,
                                  value=MINING_REWARD, signature="")

    previous_hash = blockchain.hash(last_block)
    block = blockchain.create_block(nonce, previous_hash)

    response = {
        'message': "New Block Forged",
        'block_number': block['block_number'],
        'transactions': block['transactions'],
        'nonce': block['nonce'],
        'previous_hash': block['previous_hash'],
    }
    return jsonify(response), 200


@app.route('/nodes/register', methods=['POST'])
def register_nodes():
    values = request.form
    nodes = values.get('nodes').replace(" ", "").split(',')

    if nodes is None:
        return "Error: Please supply a valid list of nodes", 400

    for node in nodes:
        blockchain.register_node(node)

    response = {
        'message': 'New nodes have been added',
        'total_nodes': [node for node in blockchain.nodes],
    }
    return jsonify(response), 201


@app.route('/nodes/resolve', methods=['GET'])
def consensus():
    replaced = blockchain.resolve_conflicts()

    if replaced:
        response = {
            'message': 'Our chain was replaced',
            'new_chain': blockchain.chain
        }
    else:
        response = {
            'message': 'Our chain is authoritative',
            'chain': blockchain.chain
        }
    return jsonify(response), 200


@app.route('/nodes/get', methods=['GET'])
def get_nodes():
    nodes = list(blockchain.nodes)
    response = {'nodes': nodes}
    return jsonify(response), 200


if __name__ == '__main__':
    from argparse import ArgumentParser

    parser = ArgumentParser()
    parser.add_argument('-p', '--port', default=5000, type=int, help='port to listen on')
    args = parser.parse_args()
    port = args.port

    app.run(host='127.0.0.1', port=port)
