import time
import datetime
import json
import random
import argparse
import sys
import operator
from hashlib import sha256
from flask import Flask, request
from requests import get, post, exceptions
import logging
from blockchain import Block, Blockchain, Transaction, TransactionEncoder
from threading import Thread

def parse_arguments():
    parser = argparse.ArgumentParser(
        "KeyChain - An overengineered key-value store "
        "with version control, powered by fancy linked-lists.")

    parser.add_argument("--miner", type=bool, default=False, nargs='?',
                        const=True, help="Starts the mining procedure.")
    parser.add_argument("--bootstrap", type=str, default=None,
                        help="Sets the address of the bootstrap node.")
    parser.add_argument("--port", type=int, default=5000,
                        help="Port on which the flask application runs")
    arguments, _ = parser.parse_known_args()

    return arguments


app = Flask(__name__)

#Disable the display of the request on prompt
log = logging.getLogger('werkzeug')
log.disabled = True
app.logger.disabled = True

#Instanciate the blockchain
arguments = parse_arguments()
node = Blockchain(miner = arguments.miner, port = arguments.port)

@app.route("/blockchain")
def get_chain():
    chain_data = []
    # Returns the blockchain and its length
    for block in node.get_blocks():
        chain_data.append(json.dumps(block.__dict__, sort_keys=True, cls=TransactionEncoder))
    return json.dumps({"length": len(chain_data), "chain": chain_data})


@app.route("/addNode")
def add_node():
    # Retrieve data from the request
    address = request.args.get("address")
    # Add the node to the network and
    # returns the hash of the last block
    node.add_node(address)
    return json.dumps(node.get_last_master_hash())
    
@app.route("/broadcast")
def message_handler():
    # Retrieve data from the request
    message_type = request.args.get('type')
    message = request.args.get('message')
    sender = request.args.get('sender')

    broadcast_deliver = node.broadcast.deliver(message_type, message, sender)
    if(not broadcast_deliver[0]):
        return json.dumps({"deliver": True})

    message_type, message, sender = broadcast_deliver[1]
    if(message_type == "transaction"):
        t = json.loads(message)
        transaction = Transaction(t["key"], t["value"], t["origin"])
        node.add_transaction(transaction, False)
        return json.dumps({"deliver": True})

    elif(message_type == 'block'):
        block = json.loads(message)
        transaction = []

        for t in block["_transactions"]:
            transaction.append(Transaction(t["key"], t["value"], t["origin"]))
        new_block = Block(block["_index"], 
                                transaction, 
                                block["_timestamp"], 
                                block["_previous_hash"],
                                block["_nonce"])
        node.confirm_block(new_block)
        return json.dumps({"deliver": True})
    else:
        return 

@app.route("/peers")
def get_peers():
    peers = []
    for peer in node.get_peers():
        peers.append(peer)
    return json.dumps({"peers": peers})

@app.route("/heartbeat")
def heartbreat():
    return json.dumps({"deliver": True})

@app.route("/put")
def put():
    # Retrieve data from the request
    data = request.get_json(force=True)
    key = data['key']
    value = data['value']
    origin = data['origin']

    # Add the transaction and returns an acknowledgement
    node.add_transaction(Transaction(key,value,origin))
    return json.dumps({"deliver": True})


@app.route("/retrieve")
def retrieve():
    value = None
    # Retrieve data from the request
    key = request.get_json(force=True)['key']
    
    # Iterate through blocks and transactions to find the 
    # most recent value corresponding to the target key
    chain = reversed(node.get_blocks())
    for block in chain:
        transactions = reversed(block.get_transactions())
        for transaction in transactions:
            if key == transaction.key:
                value = transaction.value
    return json.dumps({"value": value})


@app.route("/retrieve_all")
def retrieve_all():
    values = []
    # Retrieve data from the request
    key = request.get_json(force=True)['key']

    # Iterate through blocks and transactions to the 
    # values corresponding to the target keys
    chain = reversed(node.get_blocks())
    for block in chain:
        transactions = reversed(block.get_transactions())
        for transaction in transactions:
            if key == transaction.key:
                values.append(transaction.value)
    return json.dumps({"values": values})

if __name__ == "__main__":
    print("In init blockchain_app")
    Thread(target=node.bootstrap, args=(arguments.bootstrap,)).start()
    app.run(port=arguments.port, debug=False)
